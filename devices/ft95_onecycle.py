"""Un cycle FT95 : connexion, reception du lot, emission de la valeur candidate.

Sous-processus execute par le superviseur (contournement du bug bleak/WinRT).
Lancement : python -u -m devices.ft95_onecycle [--address MAC] [--wait-first 20] [--collect 8]
Sortie : ligne "FT95CAND {json}" pour la mesure la plus recente du lot.
"""
import argparse
import asyncio
import json
from typing import Optional

from bleak import BleakClient, BleakScanner

from devices.ft95_decode import (
    Measurement,
    decode_health_thermometer,
    decode_heuristic,
    extract_timestamp,
    make_measurement,
)

HEALTH_THERMOMETER_SERVICE = "00001809-0000-1000-8000-00805f9b34fb"
TEMPERATURE_MEASUREMENT_CHAR = "00002a1c-0000-1000-8000-00805f9b34fb"
NAME_HINTS = ("ft95", "ft 95", "beurer")


def looks_like_ft95(name: Optional[str]) -> bool:
    if not name:
        return False
    low = name.lower()
    return any(h in low for h in NAME_HINTS)


async def find_ft95(timeout: float = 15.0):
    def _filter(_, adv) -> bool:
        if looks_like_ft95(adv.local_name):
            return True
        return HEALTH_THERMOMETER_SERVICE in (adv.service_uuids or [])

    return await BleakScanner.find_device_by_filter(_filter, timeout=timeout)


class OneCycleWatcher:
    def __init__(self, on_measurement):
        self.on_measurement = on_measurement
        self.batch = []
        self.batching = False
        self._first_item: Optional[asyncio.Event] = None
        self.last_batch_size = 0

    async def _handle(self, char_uuid: str, data: bytes) -> None:
        temp = None
        if char_uuid.lower() == TEMPERATURE_MEASUREMENT_CHAR:
            temp = decode_health_thermometer(data)
            source = "health-thermometer"
        if temp is None:
            temp = decode_heuristic(data)
            source = "heuristique"
        if temp is not None:
            m = make_measurement(temp, data, source)
            if self.batching:
                ts = extract_timestamp(data)
                if ts:
                    m.device_time = ts
                self.batch.append(m)
                if self._first_item:
                    self._first_item.set()
            else:
                self.on_measurement(m)

    async def run(self, address: Optional[str], wait_first: float, collect: float):
        if address:
            device = await BleakScanner.find_device_by_address(address, timeout=15.0)
        else:
            device = await find_ft95()
        if not device:
            print("FT95 introuvable.")
            return

        print(f"Connecte a {device.name} ({device.address}) - reception du lot...")
        received = asyncio.Event()
        self._first_item = received
        self.batching = True
        self.batch = []

        try:
            async with BleakClient(device, disconnected_callback=lambda c: received.set()) as client:
                targets = []
                for service in client.services:
                    for char in service.characteristics:
                        props = char.properties
                        if char.uuid.lower() == "00002a05-0000-1000-8000-00805f9b34fb":
                            continue
                        if "indicate" in props or "notify" in props:
                            targets.append(char.uuid)
                active = 0
                for uuid in targets:
                    try:
                        await client.start_notify(
                            uuid,
                            lambda d, data, u=uuid: asyncio.ensure_future(self._handle(u, data)),
                        )
                        active += 1
                    except Exception as exc:
                        print(f"Ecoute impossible sur {uuid} : {exc}")
                if active == 0:
                    print("Aucune ecoute possible : reessayez, ou jumelez le FT95.")
                    return
                try:
                    await asyncio.wait_for(received.wait(), timeout=wait_first)
                    print("Premiere valeur recue, reception du lot...")
                    deadline = asyncio.get_event_loop().time() + collect
                    while asyncio.get_event_loop().time() < deadline:
                        n = len(self.batch)
                        await asyncio.sleep(2)
                        if len(self.batch) == n:
                            break
                except asyncio.TimeoutError:
                    print("Aucune donnee recue - deconnexion.")
                    return
        finally:
            self._first_item = None
            self.batching = False

        if not self.batch:
            return
        self.last_batch_size = len(self.batch)
        print("Lot recu : " + ", ".join(f"{m.temperature_c:.1f}" for m in self.batch))
        candidate = next((m for m in reversed(self.batch) if 30.0 <= m.temperature_c <= 43.0), None)
        if candidate is None:
            candidate = self.batch[-1]
        self.on_measurement(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ft95-onecycle")
    parser.add_argument("--address", help="Adresse MAC du FT95 (optionnelle).")
    parser.add_argument("--wait-first", type=float, default=20.0)
    parser.add_argument("--collect", type=float, default=8.0)
    args = parser.parse_args()

    def on_measurement(m: Measurement) -> None:
        print(
            "FT95CAND "
            + json.dumps(
                {
                    "temperature_c": m.temperature_c,
                    "raw": m.raw,
                    "source": m.source,
                    "size": watcher.last_batch_size,
                }
            ),
            flush=True,
        )

    watcher = OneCycleWatcher(on_measurement)
    try:
        asyncio.run(watcher.run(args.address, args.wait_first, args.collect))
    except Exception as exc:
        print(f"Erreur cycle : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
