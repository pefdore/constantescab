"""Application ConstantesCab : widget unique tension + poids + temperature.

Regroupe dans une seule fenetre flottante style Doctolib :
- tension arterielle (tensiomètre BLE type BP2/Viatom/LePu, projet bp2pro)
- poids (balance Xiaomi Mi Scale, projet miscale)
- temperature (thermometre Beurer FT95, projet beurerFT95)

La saturation (oxymetre Aicare) sera integree ulterieurement.
"""
import asyncio
import logging
import sys
import threading
import time
from typing import Optional

import tkinter as tk

from config_manager import config_manager
from devices.bp2_connector import BP2ConnectorPro, ConnectionState
from devices.scale import ScaleSupervisor
from devices.ft95 import FT95Supervisor
from floating_window import FloatingWindowCompact
from settings_dialog import show_settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('constantescab.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

try:
    from doctolib_injector import inject_to_doctolib
except ImportError:
    inject_to_doctolib = None
    logger.warning("Module doctolib_injector absent: injection Doctolib desactivee")


class ConstantesCabApplication:

    def __init__(self):
        self.connector: Optional[BP2ConnectorPro] = None
        self.connector_loop: Optional[asyncio.AbstractEventLoop] = None
        self.connector_thread: Optional[threading.Thread] = None
        self.scale_supervisor: Optional[ScaleSupervisor] = None
        self.ft95_supervisor: Optional[FT95Supervisor] = None
        self.floating_window = None
        self._root = None
        self._running = False

        logger.info("=" * 60)
        logger.info("Application ConstantesCab - Demarrage")
        logger.info("=" * 60)

    def _on_connection_state_change(self, state: ConnectionState) -> None:
        logger.info(f"Etat de connexion BP2: {state.name}")

    def _on_data_update(self, data) -> None:
        if data.is_measuring:
            logger.debug(f"Pression: {data.pressure} mmHg")

    def _on_measurement_complete(self, sys: int, dia: int, pr: int) -> None:
        logger.info(f"Mesure terminee: {sys}/{dia} mmHg, PR: {pr}")

        if config_manager.should_auto_inject():
            if inject_to_doctolib is None:
                logger.warning("Injection Doctolib ignoree: module non installe")
                return
            success = inject_to_doctolib(sys, dia, pr)
            if success:
                logger.info("Donnees injectees dans Doctolib")
            else:
                logger.warning("Echec de l'injection")

    def _start_bp2_connector(self) -> None:
        logger.info("Demarrage du connecteur tension (BP2)...")

        address = config_manager.config.bp2_address

        self.connector = BP2ConnectorPro(device_address=address)
        self.connector.on_state_change = self._on_connection_state_change
        self.connector.on_data_update = self._on_data_update
        self.connector.on_measurement_complete = self._on_measurement_complete

        def run_connector():
            self.connector_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.connector_loop)

            try:
                self.connector_loop.run_until_complete(self.connector.start())
                self.connector_loop.run_forever()
            except Exception as e:
                logger.error(f"Erreur connecteur BP2: {e}")
            finally:
                try:
                    pending = asyncio.all_tasks(self.connector_loop)
                    self.connector_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                try:
                    self.connector_loop.close()
                except Exception:
                    pass

        self.connector_thread = threading.Thread(target=run_connector, daemon=True)
        self.connector_thread.start()

        logger.info("Connecteur BP2 demarre")

    def _start_scale_supervisor(self) -> None:
        logger.info("Demarrage du superviseur poids (Mi Scale)...")
        self.scale_supervisor = ScaleSupervisor()
        self.scale_supervisor.start()

    def _start_ft95_supervisor(self) -> None:
        logger.info("Demarrage du superviseur temperature (FT95)...")
        self.ft95_supervisor = FT95Supervisor()
        self.ft95_supervisor.start()

    def _open_settings(self) -> None:
        if self.floating_window and hasattr(self.floating_window, 'root'):
            self.floating_window.root.after(0, self._show_settings_dialog)
        elif self._root:
            self._root.after(0, self._show_settings_dialog)

    def _show_settings_dialog(self) -> None:
        try:
            parent = None
            if self.floating_window and hasattr(self.floating_window, 'root'):
                parent = self.floating_window.root
            elif self._root:
                parent = self._root
            show_settings(parent, on_save=self._on_settings_saved,
                          on_bp2_device=self._on_bp2_device_configured)
        except Exception as e:
            logger.error(f"Erreur ouverture parametres: {e}")
            import traceback
            traceback.print_exc()

    def _on_settings_saved(self) -> None:
        logger.info("Parametres sauvegardes")

    def _on_bp2_device_configured(self, address: str, name: str) -> None:
        logger.info(f"Nouvel appareil tension configure: {name} ({address})")
        if self.connector and self.connector_loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.connector.connect_to_device(address), self.connector_loop)
                logger.info("Reconnexion vers le nouvel appareil en cours...")
            except RuntimeError:
                logger.warning("Boucle connecteur indisponible: "
                               "le nouvel appareil sera utilise au prochain demarrage")

    def run(self) -> None:
        try:
            self._running = True

            self._start_bp2_connector()
            self._start_scale_supervisor()
            self._start_ft95_supervisor()

            if config_manager.config.show_floating_window:
                logger.info("Lancement de l'interface...")
                self.floating_window = FloatingWindowCompact(on_settings=self._open_settings)
                self.floating_window.run()
            else:
                logger.info("Fenetre flottante desactivee: l'app reste en tache de fond")
                while self._running:
                    time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Interruption utilisateur")
        except Exception as e:
            logger.error(f"Erreur application: {e}", exc_info=True)
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        logger.info("Arret de l'application...")
        self._running = False

        if self.scale_supervisor:
            self.scale_supervisor.stop()

        if self.ft95_supervisor:
            self.ft95_supervisor.stop()

        if self.connector and self.connector_loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.connector.stop(), self.connector_loop)
                future.result(timeout=3)
            except Exception as e:
                logger.error(f"Erreur lors de l'arret du connecteur: {e}")

            try:
                self.connector_loop.call_soon_threadsafe(self.connector_loop.stop)
            except RuntimeError:
                pass

        logger.info("Application arretee")


def main():
    try:
        import bleak
        import pywinauto
        import pyautogui
    except ImportError as e:
        print(f"Erreur: Dependance manquante - {e}")
        print("Veuillez installer les dependances: pip install -r requirements.txt")
        sys.exit(1)

    app = ConstantesCabApplication()
    app.run()


if __name__ == "__main__":
    main()
