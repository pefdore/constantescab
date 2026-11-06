"""Worker Mi Scale : sous-processus qui se connecte a la balance et imprime chaque poids.

Lancement : python -u -m devices.scale_worker --address XX:XX:XX:XX:XX:XX
Sortie : lignes "Weight: 75.20" (a chaque notification recue).
"""
import argparse
import asyncio
import logging

from bleak import BleakClient, BleakScanner

BODY_COMPOSITION_MEASUREMENT_UUID = "00002a9c-0000-1000-8000-00805f9b34fb"


def parse_scale_measurement(buffer: bytearray) -> float:
    return ((buffer[12] << 8) + buffer[11]) / 200


def is_stabilized(buffer: bytearray) -> bool:
    return (buffer[1] & 32) > 0


def notification_handler(characteristic, data: bytearray):
    if len(data) < 13:
        return
    weight = parse_scale_measurement(data)
    print(f"Weight: {weight:.2f}", flush=True)


async def connect_and_measure(address: str):
    device = await BleakScanner.find_device_by_address(address, timeout=20.0)
    if not device:
        logging.error("Balance %s introuvable.", address)
        return

    disconnected_event = asyncio.Event()

    def disconnected_callback(_client):
        disconnected_event.set()

    async with BleakClient(device, disconnected_callback=disconnected_callback) as client:
        if not client.is_connected:
            logging.error("Impossible de se connecter a %s", address)
            return
        try:
            await client.start_notify(BODY_COMPOSITION_MEASUREMENT_UUID, notification_handler)
            await disconnected_event.wait()
        except Exception as e:
            logging.error("Erreur durant la communication : %s", e)


def main():
    parser = argparse.ArgumentParser(prog="scale-worker")
    parser.add_argument("--address", type=str, required=True)
    args = parser.parse_args()
    asyncio.run(connect_and_measure(args.address))


if __name__ == "__main__":
    main()
