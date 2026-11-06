"""Superviseur FT95 : boucle de cycles en thread, detection des nouvelles mesures,
copie presse-papiers, historisation et mise a jour du statut pour l'interface."""
import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from config_manager import config_manager, get_data_dir
from devices.ft95_decode import Measurement
from devices.ft95_storage import MeasurementStore
from devices.status import write_status

logger = logging.getLogger(__name__)


class FT95Supervisor(threading.Thread):
    def __init__(self, on_measurement=None):
        super().__init__(daemon=True, name="FT95Supervisor")
        self._stop_event = threading.Event()
        self.on_measurement = on_measurement
        data_dir = get_data_dir()
        self.store = MeasurementStore(
            str(data_dir / "mesures.csv"),
            str(data_dir / "mesures.jsonl"),
        )
        self._seen = set()
        self._prev_batch_size = 0
        self.last_temperature = None
        self.last_measured_at = None

    def run(self):
        while not self._stop_event.is_set():
            config = config_manager.config
            cmd = [
                sys.executable, "-u", "-m", "devices.ft95_onecycle",
                "--wait-first", str(config.ft95_wait_first),
                "--collect", str(config.ft95_collect),
            ]
            if config.ft95_address:
                cmd += ["--address", config.ft95_address]

            write_status('ft95', {"state": "connexion", "connected": True,
                                  "temperature_c": self.last_temperature,
                                  "measured_at": self.last_measured_at})

            try:
                creationflags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags = subprocess.CREATE_NO_WINDOW
                proc = subprocess.run(
                    cmd, capture_output=True, text=True,
                    cwd=str(Path(__file__).resolve().parent.parent),
                    creationflags=creationflags,
                )
                for line in proc.stdout.splitlines():
                    if line.startswith("FT95CAND "):
                        obj = json.loads(line[len("FT95CAND "):])
                        self._handle_candidate(obj)
                    elif line.strip():
                        logger.info("FT95: %s", line)
            except Exception as exc:
                logger.error("Cycle FT95 interrompu (%s)", exc)
                write_status('ft95', {"state": "erreur", "connected": False,
                                      "temperature_c": self.last_temperature,
                                      "measured_at": self.last_measured_at})
                self._stop_event.wait(5.0)
                continue

            write_status('ft95', {"state": "libre", "connected": False,
                                  "temperature_c": self.last_temperature,
                                  "measured_at": self.last_measured_at})
            self._stop_event.wait(max(1.0, config_manager.config.ft95_free))

    def _handle_candidate(self, obj: dict) -> None:
        grew = obj.get("size", 0) > self._prev_batch_size
        is_new = obj["raw"] not in self._seen or grew
        self._prev_batch_size = max(self._prev_batch_size, obj.get("size", 0))
        self._seen.add(obj["raw"])
        if len(self._seen) > 500:
            self._seen = set(list(self._seen)[-250:])

        if not is_new:
            logger.info("Lot deja traite - pas de nouvelle mesure.")
            return

        m = Measurement(
            temperature_c=obj["temperature_c"],
            timestamp=datetime.now(),
            raw=obj["raw"],
            source=obj.get("source", ""),
        )
        self.last_temperature = m.temperature_c
        self.last_measured_at = m.timestamp.isoformat()

        self.store.save(m)
        write_status('ft95', {"state": "libre", "connected": False,
                              "temperature_c": self.last_temperature,
                              "measured_at": self.last_measured_at})

        if config_manager.config.ft95_copy_clipboard:
            from clipboard import copy_text
            copy_text(f"{m.temperature_c:.1f}")

        logger.info("Nouvelle mesure : %s", m.display())

        if self.on_measurement:
            try:
                self.on_measurement(m)
            except Exception as e:
                logger.error("Erreur callback on_measurement: %s", e)

    def stop(self):
        self._stop_event.set()
