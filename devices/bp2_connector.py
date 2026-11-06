"""Connecteur BP2 (tension arterielle) reutilise du projet bp2pro, branche sur la config unifiee."""
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum, auto
from bleak import BleakClient, BleakScanner

from config_manager import config_manager
from devices.status import write_status

logger = logging.getLogger(__name__)

SERVICE_UUID = "14839AC4-7D7E-415C-9A42-167340CF2339"
V_WRITE = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
V_NOTIFY = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"


class ConnectionState(Enum):
    DISCONNECTED = auto()
    SCANNING = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    MONITORING = auto()
    ERROR = auto()
    RECONNECTING = auto()


@dataclass
class BP2Data:
    pressure: float = 0.0
    is_measuring: bool = False
    battery: int = 0
    sys: Optional[int] = None
    dia: Optional[int] = None
    pr: Optional[int] = None
    last_update: Optional[datetime] = None
    measured_at: Optional[datetime] = None


class BP2ConnectorPro:
    """Connecteur BP2 : boucle de supervision unique, deconnexion propre
    avant chaque nouvelle tentative, reconnexion rapide et persistante."""

    def __init__(self, device_address: Optional[str] = None):
        self.device_address = device_address
        self.client: Optional[BleakClient] = None
        self.state = ConnectionState.DISCONNECTED
        self.data = BP2Data()

        self.on_state_change: Optional[Callable[[ConnectionState], None]] = None
        self.on_data_update: Optional[Callable[[BP2Data], None]] = None
        self.on_measurement_complete: Optional[Callable[[int, int, int], None]] = None

        self._connection_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._client_lock = asyncio.Lock()

        self._reconnect_delay = config_manager.config.reconnect_delay_seconds or 2.0
        self._max_reconnect_delay = config_manager.config.max_reconnect_delay_seconds or 5.0
        self._reconnect_backoff = 1.5
        self._heartbeat_interval = 2.5

        self._last_status_write = 0.0
        self._status_min_interval = 0.25

        self._stop_event = asyncio.Event()

        logger.info("BP2ConnectorPro initialise")

    def _crc8(self, data: bytes) -> int:
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x07
                else:
                    crc <<= 1
                crc &= 0xFF
        return crc

    def _make_a5_cmd(self, cmd_byte: int, seq: int, data: Optional[bytes] = None) -> bytes:
        if data is None:
            data = b''
        packet = bytearray([0xA5, 0x08, cmd_byte, 0x00, seq, 0x00, 0x00])
        packet.extend(data)
        packet.append(self._crc8(packet))
        return bytes(packet)

    def _set_state(self, new_state: ConnectionState) -> None:
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            logger.info(f"Etat change: {old_state.name} -> {new_state.name}")
            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    logger.error(f"Erreur callback on_state_change: {e}")

    async def _update_status_file(self) -> None:
        now = time.monotonic()
        if now - self._last_status_write < self._status_min_interval:
            return
        self._last_status_write = now

        write_status('bp2', {
            "state": self.state.name,
            "connected": self.state in (ConnectionState.CONNECTED, ConnectionState.MONITORING),
            "pressure": self.data.pressure,
            "is_measuring": self.data.is_measuring,
            "battery": self.data.battery,
            "last_result": {
                "sys": self.data.sys,
                "dia": self.data.dia,
                "pr": self.data.pr,
                "measured_at": self.data.measured_at.isoformat() if self.data.measured_at else None
            } if self.data.sys else None,
        })

    def _notification_handler(self, sender: Any, data: bytes) -> None:
        if len(data) < 2 or data[0] != 0xA5:
            return

        cmd = data[2]

        if len(data) >= 20:
            pressure_raw = data[18] + (data[19] << 8)
            pressure = pressure_raw * 0.00931932859643703

            if 10 <= pressure <= 300:
                self.data.pressure = round(pressure, 1)
                self.data.is_measuring = True
                self.data.last_update = datetime.now()
            elif self.data.is_measuring and pressure < 10:
                self.data.is_measuring = False

                if self.on_data_update:
                    try:
                        self.on_data_update(self.data)
                    except Exception as e:
                        logger.error(f"Erreur callback on_data_update: {e}")

        if cmd == 0x00 and len(data) >= 30:
            sys_val = data[20]
            dia_val = data[22]
            pr_val = data[26]

            if 70 <= sys_val <= 220 and 40 <= dia_val <= 130:
                is_new_measurement = (
                    self.data.sys is None
                    or sys_val != self.data.sys
                    or dia_val != self.data.dia
                    or pr_val != self.data.pr
                )

                self.data.sys = sys_val
                self.data.dia = dia_val
                self.data.pr = pr_val
                self.data.is_measuring = False

                if is_new_measurement:
                    self.data.measured_at = datetime.now()
                    logger.info(f"Mesure complete: {sys_val}/{dia_val} mmHg, PR: {pr_val}")

                    if self.on_measurement_complete:
                        try:
                            self.on_measurement_complete(sys_val, dia_val, pr_val)
                        except Exception as e:
                            logger.error(f"Erreur callback on_measurement_complete: {e}")
                else:
                    logger.info(f"Re-emission du dernier resultat ignoree: {sys_val}/{dia_val}")

        if len(data) > 9:
            batt = data[9]
            if 0 <= batt <= 100:
                self.data.battery = batt

    async def _heartbeat_loop(self) -> None:
        seq = 0x61
        while not self._stop_event.is_set():
            await asyncio.sleep(self._heartbeat_interval)
            if self._stop_event.is_set():
                break
            try:
                client = self.client
                if client and client.is_connected:
                    cmd = self._make_a5_cmd(0x00, seq)
                    await client.write_gatt_char(V_WRITE, cmd)
                    seq = (seq + 1) % 0xFF
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Heartbeat interrompu: {e}")
                self._set_state(ConnectionState.ERROR)
                return

    def _on_disconnect(self, client: Any) -> None:
        logger.warning("Deconnexion BLE detectee")
        self._set_state(ConnectionState.RECONNECTING)

    async def _disconnect_client(self) -> None:
        async with self._client_lock:
            client = self.client
            self.client = None
            if client:
                try:
                    if client.is_connected:
                        try:
                            await client.disconnect()
                        except Exception as e:
                            logger.debug(f"Deconnexion deja faite: {e}")
                except Exception as e:
                    logger.debug(f"Erreur verification is_connected: {e}")

    async def _find_bp2_device(self) -> Optional[Any]:
        logger.info("Recherche d'appareils BP2...")

        try:
            if self.device_address:
                try:
                    device = await BleakScanner.find_device_by_address(
                        self.device_address, timeout=6.0
                    )
                    if device:
                        logger.info(f"BP2 configure trouve: {device.name or self.device_address}")
                        return device
                except Exception as e:
                    logger.debug(f"Recherche par adresse echouee: {e}")

            devices = await BleakScanner(
                service_uuids=[SERVICE_UUID],
                timeout=8.0
            ).discover()

            bp2_devices = []
            for device in devices:
                name = device.name or ""
                if ("bp2" in name.lower() or "viatom" in name.lower()
                        or "lepu" in name.lower()):
                    bp2_devices.append(device)
                    logger.info(f"BP2 trouve: {name} ({device.address})")

            if bp2_devices:
                if self.device_address:
                    for dev in bp2_devices:
                        if dev.address == self.device_address:
                            return dev
                return bp2_devices[0]

            devices = await BleakScanner(timeout=6.0).discover()
            for device in devices:
                name = device.name or ""
                if "bp2" in name.lower():
                    logger.info(f"BP2 trouve (scan general): {name} ({device.address})")
                    return device

            logger.warning("Aucun BP2 trouve")
            return None

        except Exception as e:
            logger.error(f"Erreur lors du scan: {e}")
            return None

    async def _connect_device(self, device: Any) -> bool:
        try:
            await self._disconnect_client()

            self._set_state(ConnectionState.CONNECTING)

            client = BleakClient(device, disconnected_callback=self._on_disconnect)
            await client.connect(timeout=15.0)

            if not client.is_connected:
                logger.error("Echec de la connexion")
                self._set_state(ConnectionState.ERROR)
                try:
                    await client.disconnect()
                except Exception:
                    pass
                return False

            async with self._client_lock:
                self.client = client

            logger.info(f"Connecte a {device.name or 'BP2'}")

            await client.start_notify(V_NOTIFY, self._notification_handler)

            self._set_state(ConnectionState.CONNECTED)
            await self._update_status_file()

            if self._heartbeat_task and not self._heartbeat_task.done():
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            self._set_state(ConnectionState.MONITORING)
            return True

        except Exception as e:
            logger.error(f"Erreur connexion: {e}")
            self._set_state(ConnectionState.ERROR)
            await self._disconnect_client()
            return False

    async def _reconnect_loop(self) -> None:
        auto_reconnect = config_manager.config.auto_reconnect
        self._reconnect_delay = config_manager.config.reconnect_delay_seconds or 2.0
        self._max_reconnect_delay = config_manager.config.max_reconnect_delay_seconds or 5.0

        if not auto_reconnect:
            logger.info("Reconnexion automatique desactivee (parametres)")
            self._set_state(ConnectionState.DISCONNECTED)
            await self._update_status_file()
            return

        delay = self._reconnect_delay

        while not self._stop_event.is_set():
            self._set_state(ConnectionState.RECONNECTING)
            await self._update_status_file()

            try:
                device = await self._find_bp2_device()

                if device:
                    logger.info(f"Tentative de connexion a {device.address}")
                    if await self._connect_device(device):
                        self.device_address = device.address
                        logger.info("Reconnexion reussie!")
                        await self._update_status_file()
                        return

                logger.info(f"Nouvelle tentative dans {delay:.1f}s...")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay
                    )
                    return
                except asyncio.TimeoutError:
                    pass

                delay = min(delay * self._reconnect_backoff,
                            self._max_reconnect_delay)

            except Exception as e:
                logger.error(f"Erreur reconnexion: {e}")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=delay
                    )
                    return
                except asyncio.TimeoutError:
                    pass

    async def start(self) -> None:
        logger.info("Demarrage du connecteur BP2 Pro")

        if self._connection_task and not self._connection_task.done():
            logger.warning("Le connecteur est deja demarre")
            return

        self._stop_event.clear()
        self._connection_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.state in (ConnectionState.DISCONNECTED,
                                  ConnectionState.ERROR,
                                  ConnectionState.RECONNECTING):
                    await self._reconnect_loop()

                if self.state == ConnectionState.MONITORING:
                    if not self.client or not self.client.is_connected:
                        logger.warning("Connexion perdue")
                        self._set_state(ConnectionState.ERROR)
                    else:
                        await self._update_status_file()

                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Erreur boucle principale: {e}", exc_info=True)
                self._set_state(ConnectionState.ERROR)
                await asyncio.sleep(1.0)

    async def stop(self) -> None:
        logger.info("Arret du connecteur BP2 Pro")

        self._stop_event.set()

        tasks = []
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            tasks.append(self._heartbeat_task)
        if self._connection_task and not self._connection_task.done():
            self._connection_task.cancel()
            tasks.append(self._connection_task)

        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Erreur lors de l'annulation des taches: {e}")

        await self._disconnect_client()

        self._set_state(ConnectionState.DISCONNECTED)
        try:
            await self._update_status_file()
        except Exception:
            pass

    async def connect_to_device(self, address: str) -> bool:
        self.device_address = address

        if self.state != ConnectionState.DISCONNECTED:
            await self.stop()

        await self.start()
        return True
