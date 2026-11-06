"""Superviseur Mi Scale : boucle persistante en thread, relance le worker en sous-processus."""
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from config_manager import config_manager
from devices.status import write_status

logger = logging.getLogger(__name__)


class ScaleSupervisor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="ScaleSupervisor")
        self._stop_event = threading.Event()
        self.last_weight = None
        self.last_measured_at = None
        self.connected = False

    def run(self):
        while not self._stop_event.is_set():
            address = config_manager.config.scale_address
            if not address:
                write_status('scale', {"connected": False, "weight": None,
                                      "measured_at": None, "state": "non configure"})
                self._stop_event.wait(5.0)
                continue

            self._run_worker(address)
            if self._stop_event.is_set():
                break
            self._stop_event.wait(3.0)

    def _run_worker(self, address: str):
        cmd = [sys.executable, "-u", "-m", "devices.scale_worker", "--address", address]
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, universal_newlines=True,
                cwd=str(Path(__file__).resolve().parent.parent),
                creationflags=creationflags,
            )
        except Exception as e:
            logger.error("Impossible de lancer le worker balance: %s", e)
            self.connected = False
            write_status('scale', {"connected": False, "state": "erreur worker"})
            return

        self.connected = True
        write_status('scale', {"connected": True, "state": "connexion",
                               "weight": self.last_weight,
                               "measured_at": self.last_measured_at})

        try:
            for line in iter(process.stdout.readline, ''):
                if self._stop_event.is_set():
                    process.kill()
                    break
                if "Weight:" in line:
                    try:
                        weight = float(line.split("Weight:")[1].strip().split(" ")[0])
                        self.last_weight = weight
                        self.last_measured_at = datetime.now().isoformat()
                        write_status('scale', {"connected": True, "state": "connecte",
                                               "weight": weight,
                                               "measured_at": self.last_measured_at})
                    except (IndexError, ValueError):
                        pass
            process.wait()
        except Exception as e:
            logger.error("Worker balance interrompu: %s", e)
        finally:
            if process.poll() is None:
                process.kill()
            self.connected = False
            write_status('scale', {"connected": False, "state": "reconnexion",
                                   "weight": self.last_weight,
                                   "measured_at": self.last_measured_at})

    def stop(self):
        self._stop_event.set()
