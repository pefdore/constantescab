"""Panneau de configuration commun ConstantesCab : un onglet par appareil.

Onglets : Tension (BP2), Poids (Mi Scale), Temperature (FT95), Affichage (commun).
"""
import asyncio
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Callable, List, Optional

from config_manager import config_manager, get_data_dir
from devices.ft95_storage import count_history
from devices.status import read_status

BP2_NAME_FILTERS = ("bp2", "viatom", "lepu")
FT95_NAME_FILTERS = ("ft95", "ft 95", "beurer")
HEALTH_THERMOMETER_SERVICE = "00001809-0000-1000-8000-00805f9b34fb"


@dataclass
class BluetoothDevice:
    name: str
    address: str
    rssi: int


class BluetoothScanner:
    """Scanner Bluetooth asynchrone avec filtre de nom optionnel."""

    def __init__(self, name_filters: Optional[tuple] = None, service_uuid: Optional[str] = None):
        self.name_filters = name_filters
        self.service_uuid = service_uuid
        self._scanning = False
        self.devices: List[BluetoothDevice] = []
        self.on_device_found: Optional[Callable[[BluetoothDevice], None]] = None
        self.on_scan_complete: Optional[Callable[[], None]] = None

    async def scan(self, duration: float = 10.0) -> List[BluetoothDevice]:
        from bleak import BleakScanner

        self._scanning = True
        self.devices = []

        try:
            kwargs = {"timeout": duration}
            if self.service_uuid:
                kwargs["service_uuids"] = [self.service_uuid]
            devices = await BleakScanner(**kwargs).discover()

            for device in devices:
                name = device.name or ""
                if self.name_filters and not any(f in name.lower() for f in self.name_filters):
                    continue
                rssi = getattr(device, 'rssi', None) or -100
                bt_device = BluetoothDevice(
                    name=name or "Inconnu",
                    address=device.address,
                    rssi=rssi
                )
                self.devices.append(bt_device)

                if self.on_device_found:
                    self.on_device_found(bt_device)
        except Exception as e:
            print(f"Erreur scan: {e}")

        self._scanning = False

        if self.on_scan_complete:
            self.on_scan_complete()

        return self.devices

    def is_scanning(self) -> bool:
        return self._scanning


class DeviceTab:
    """Onglet generique : scan, liste d'appareils, selection et connexion."""

    def __init__(self, parent: ttk.Frame, app_settings: 'SettingsDialog',
                 title: str, name_filters: Optional[tuple], service_uuid: Optional[str] = None):
        self.app = app_settings
        self.scanner = BluetoothScanner(name_filters=name_filters, service_uuid=service_uuid)
        self.devices: List[BluetoothDevice] = []
        self.selected_device: Optional[BluetoothDevice] = None

        frame = ttk.LabelFrame(parent, text=title, padding="6")
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        frame.columnconfigure(0, weight=1)

        columns = ('name', 'address', 'signal')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', height=4)
        self.tree.heading('name', text='Nom')
        self.tree.heading('address', text='Adresse MAC')
        self.tree.heading('signal', text='Signal')
        self.tree.column('name', width=150, minwidth=100)
        self.tree.column('address', width=150, minwidth=100)
        self.tree.column('signal', width=100, minwidth=80)
        self.tree.grid(row=0, column=0, sticky="ew", pady=3)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=3)
        self.tree.configure(yscrollcommand=scrollbar.set)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=3)

        self.scan_btn = ttk.Button(btn_frame, text="Scanner", command=self._start_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.connect_btn = ttk.Button(btn_frame, text="Utiliser cet appareil",
                                      command=self._connect_device, state='disabled')
        self.connect_btn.pack(side=tk.LEFT)

        self.scan_status = ttk.Label(btn_frame, text="Pret", foreground='gray')
        self.scan_status.pack(side=tk.RIGHT)

        self.configured_label = ttk.Label(frame, text="Aucun appareil configure", foreground='gray')
        self.configured_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.tree.bind('<<TreeviewSelect>>', self._on_device_select)

    def _start_scan(self) -> None:
        if self.scanner.is_scanning():
            return

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.devices = []

        self.scan_btn.config(state='disabled')
        self.scan_status.config(text="Scan en cours...", foreground='blue')

        def on_device_found(device):
            self.app._ui_queue.put(('device_found', (self, device)))

        def on_scan_complete():
            self.app._ui_queue.put(('scan_complete', self))

        self.scanner.on_device_found = on_device_found
        self.scanner.on_scan_complete = on_scan_complete

        def run_scan():
            asyncio.run(self.scanner.scan(duration=10.0))

        threading.Thread(target=run_scan, daemon=True).start()

    def add_device(self, device: BluetoothDevice) -> None:
        self.devices.append(device)

        signal_text = f"{device.rssi} dBm"
        if device.rssi > -60:
            signal_text += " (Excellent)"
        elif device.rssi > -80:
            signal_text += " (Bon)"
        else:
            signal_text += " (Faible)"

        self.tree.insert('', tk.END, values=(device.name, device.address, signal_text))

    def finish_scan(self) -> None:
        self.scan_btn.config(state='normal')

        if self.devices:
            self.scan_status.config(text=f"{len(self.devices)} appareil(s) trouve(s)", foreground='green')
        else:
            self.scan_status.config(text="Aucun appareil trouve", foreground='red')

    def _on_device_select(self, event=None) -> None:
        selection = self.tree.selection()
        if selection:
            item = self.tree.item(selection[0])
            values = item['values']

            for device in self.devices:
                if device.address == values[1]:
                    self.selected_device = device
                    self.connect_btn.config(state='normal')
                    return

        self.selected_device = None
        self.connect_btn.config(state='disabled')

    def _connect_device(self) -> None:
        if not self.selected_device:
            return

        self.app.on_device_selected(self, self.selected_device)

    def set_configured(self, text: str) -> None:
        self.configured_label.config(text=text, foreground='green')


class SettingsDialog:
    """Boite de dialogue des parametres : un onglet par appareil + affichage commun."""

    def __init__(self, parent: Optional[tk.Tk] = None,
                 on_save: Optional[Callable[[], None]] = None,
                 on_bp2_device: Optional[Callable[[str, str], None]] = None):
        self.parent = parent
        self.on_save = on_save
        self.on_bp2_device = on_bp2_device
        self._ui_queue = queue.Queue()

        if parent:
            self.window = tk.Toplevel(parent)
            self.window.transient(parent)
        else:
            self.window = tk.Tk()

        self.window.title("Parametres ConstantesCab")
        self.window.attributes("-topmost", True)

        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        window_width = min(680, int(screen_width * 0.9))
        window_height = min(620, int(screen_height * 0.9))

        self.window.geometry(f"{window_width}x{window_height}")
        self.window.minsize(560, 420)
        self.window.resizable(True, True)

        if parent:
            self.window.grab_set()

        self.window.update_idletasks()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.window.geometry(f'{window_width}x{window_height}+{x}+{y}')

        self._create_ui()
        self._load_config()
        self._check_queue()

    def _create_ui(self) -> None:
        main_frame = ttk.Frame(self.window, padding="6")
        main_frame.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_bp2 = ttk.Frame(notebook, padding="6")
        notebook.add(tab_bp2, text="Tension (BP2)")
        self.tab_bp2 = DeviceTab(tab_bp2, self, "Appareil de tension",
                                 BP2_NAME_FILTERS,
                                 "14839AC4-7D7E-415C-9A42-167340CF2339")
        self._create_bp2_extra(tab_bp2)

        tab_scale = ttk.Frame(notebook, padding="6")
        notebook.add(tab_scale, text="Poids (Mi Scale)")
        self.tab_scale = DeviceTab(tab_scale, self, "Balance", ("mi scale", "mi body", "xiaomi", "scale"))
        self._create_scale_extra(tab_scale)

        tab_ft95 = ttk.Frame(notebook, padding="6")
        notebook.add(tab_ft95, text="Temperature (FT95)")
        self.tab_ft95 = DeviceTab(tab_ft95, self, "Thermometre",
                                  FT95_NAME_FILTERS, HEALTH_THERMOMETER_SERVICE)
        self._create_ft95_extra(tab_ft95)

        tab_display = ttk.Frame(notebook, padding="6")
        notebook.add(tab_display, text="Affichage")
        self._create_display_tab(tab_display)

        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(6, 0))

        ttk.Button(action_frame, text="Sauvegarder",
                   command=self._save).pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Button(action_frame, text="Annuler",
                   command=self._cancel).pack(side=tk.RIGHT)

    def _create_bp2_extra(self, parent: ttk.Frame) -> None:
        doctolib_frame = ttk.LabelFrame(parent, text="Integration Doctolib", padding="6")
        doctolib_frame.pack(fill=tk.BOTH, padx=4, pady=4)
        doctolib_frame.columnconfigure(0, weight=1)

        self.auto_inject_var = tk.BooleanVar(value=True)
        self.play_sound_var = tk.BooleanVar(value=True)
        self.block_keyboard_var = tk.BooleanVar(value=True)

        self.inject_cb = ttk.Checkbutton(doctolib_frame,
                text="Injecter automatiquement la tension dans Doctolib",
                variable=self.auto_inject_var)
        self.inject_cb.grid(row=0, column=0, sticky="w", pady=1)

        self.sound_cb = ttk.Checkbutton(doctolib_frame,
                text="Jouer un son avant l'injection (alerte utilisateur)",
                variable=self.play_sound_var)
        self.sound_cb.grid(row=1, column=0, sticky="w", pady=1)

        self.block_cb = ttk.Checkbutton(doctolib_frame,
                text="Bloquer le clavier pendant l'injection",
                variable=self.block_keyboard_var)
        self.block_cb.grid(row=2, column=0, sticky="w", pady=1)

        try:
            import doctolib_injector  # noqa: F401
            doctolib_available = True
        except ImportError:
            doctolib_available = False

        if not doctolib_available:
            for cb in (self.inject_cb, self.sound_cb, self.block_cb):
                cb.state(['disabled'])
            ttk.Label(doctolib_frame,
                      text="Module d'injection non installe: options inactives.",
                      foreground='gray').grid(row=3, column=0, sticky="w", pady=(4, 0))

        conn_frame = ttk.LabelFrame(parent, text="Connexion", padding="6")
        conn_frame.pack(fill=tk.BOTH, padx=4, pady=4)
        conn_frame.columnconfigure(0, weight=1)

        self.auto_reconnect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(conn_frame,
                text="Reconnexion automatique en cas de deconnexion",
                variable=self.auto_reconnect_var).grid(row=0, column=0, sticky="w", pady=1)

        delay_frame = ttk.Frame(conn_frame)
        delay_frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.reconnect_delay_var = tk.StringVar(value="2.0")
        self.max_reconnect_delay_var = tk.StringVar(value="5.0")

        ttk.Label(delay_frame, text="Delai entre tentatives (s):").pack(side=tk.LEFT)
        ttk.Spinbox(delay_frame, from_=1.0, to=30.0, increment=0.5, width=5,
                    textvariable=self.reconnect_delay_var).pack(side=tk.LEFT, padx=(4, 10))

        ttk.Label(delay_frame, text="Delai max (s):").pack(side=tk.LEFT)
        ttk.Spinbox(delay_frame, from_=2.0, to=60.0, increment=1.0, width=5,
                    textvariable=self.max_reconnect_delay_var).pack(side=tk.LEFT, padx=4)

        self.bp2_status_label = ttk.Label(conn_frame, text="Etat: inconnu", foreground='gray')
        self.bp2_status_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _create_scale_extra(self, parent: ttk.Frame) -> None:
        info_frame = ttk.LabelFrame(parent, text="Fonctionnement", padding="6")
        info_frame.pack(fill=tk.BOTH, padx=4, pady=4)

        ttk.Label(info_frame,
                  text="La balance est surveillee en continu : montez dessus, le poids "
                       "s'affiche des qu'il est stabilise.",
                  wraplength=560).pack(anchor="w")

        self.scale_status_label = ttk.Label(info_frame, text="Etat: inconnu", foreground='gray')
        self.scale_status_label.pack(anchor="w", pady=(6, 0))

    def _create_ft95_extra(self, parent: ttk.Frame) -> None:
        cycle_frame = ttk.LabelFrame(parent, text="Cycle de mesure", padding="6")
        cycle_frame.pack(fill=tk.BOTH, padx=4, pady=4)
        cycle_frame.columnconfigure(1, weight=1)

        self.ft95_copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cycle_frame,
                text="Copier chaque nouvelle temperature dans le presse-papiers (Ctrl+V dans Doctolib)",
                variable=self.ft95_copy_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=1)

        timing_frame = ttk.Frame(cycle_frame)
        timing_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        self.ft95_wait_first_var = tk.StringVar(value="20.0")
        self.ft95_collect_var = tk.StringVar(value="8.0")
        self.ft95_free_var = tk.StringVar(value="25.0")

        ttk.Label(timing_frame, text="Attente 1re valeur (s):").pack(side=tk.LEFT)
        ttk.Spinbox(timing_frame, from_=5.0, to=60.0, increment=1.0, width=5,
                    textvariable=self.ft95_wait_first_var).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(timing_frame, text="Reception du lot (s):").pack(side=tk.LEFT)
        ttk.Spinbox(timing_frame, from_=2.0, to=30.0, increment=1.0, width=5,
                    textvariable=self.ft95_collect_var).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(timing_frame, text="Thermometre libre (s):").pack(side=tk.LEFT)
        ttk.Spinbox(timing_frame, from_=5.0, to=120.0, increment=1.0, width=5,
                    textvariable=self.ft95_free_var).pack(side=tk.LEFT, padx=4)

        hist_frame = ttk.LabelFrame(parent, text="Historique", padding="6")
        hist_frame.pack(fill=tk.BOTH, padx=4, pady=4)

        data_dir = get_data_dir()
        n = count_history(str(data_dir / "mesures.jsonl"))
        ttk.Label(hist_frame,
                  text=f"{n} mesure(s) enregistree(s) - {data_dir / 'mesures.csv'}",
                  foreground='gray').pack(anchor="w")

        self.ft95_status_label = ttk.Label(hist_frame, text="Etat: inconnu", foreground='gray')
        self.ft95_status_label.pack(anchor="w", pady=(6, 0))

    def _create_display_tab(self, parent: ttk.Frame) -> None:
        display_frame = ttk.LabelFrame(parent, text="Fenetre flottante", padding="6")
        display_frame.pack(fill=tk.BOTH, padx=4, pady=4)
        display_frame.columnconfigure(0, weight=1)

        self.show_floating_window_var = tk.BooleanVar(value=True)
        self.show_only_doctolib_var = tk.BooleanVar(value=True)
        self.save_window_position_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(display_frame,
                text="Afficher la fenetre flottante (tension, poids, temperature)",
                variable=self.show_floating_window_var).grid(row=0, column=0, sticky="w", pady=1)

        ttk.Checkbutton(display_frame,
                text="Afficher la fenetre uniquement si Doctolib est ouvert",
                variable=self.show_only_doctolib_var).grid(row=1, column=0, sticky="w", pady=1)

        ttk.Checkbutton(display_frame,
                text="Sauvegarder la position de la fenetre (au prochain lancement)",
                variable=self.save_window_position_var).grid(row=2, column=0, sticky="w", pady=1)

    def _load_config(self) -> None:
        config = config_manager.config

        self.auto_inject_var.set(config.auto_inject_doctolib)
        self.play_sound_var.set(config.play_sound_before_injection)
        self.block_keyboard_var.set(config.block_keyboard_during_injection)
        self.auto_reconnect_var.set(config.auto_reconnect)
        self.reconnect_delay_var.set(str(config.reconnect_delay_seconds))
        self.max_reconnect_delay_var.set(str(config.max_reconnect_delay_seconds))

        self.ft95_copy_var.set(config.ft95_copy_clipboard)
        self.ft95_wait_first_var.set(str(config.ft95_wait_first))
        self.ft95_collect_var.set(str(config.ft95_collect))
        self.ft95_free_var.set(str(config.ft95_free))

        self.show_floating_window_var.set(config.show_floating_window)
        self.show_only_doctolib_var.set(config.show_only_doctolib)
        self.save_window_position_var.set(config.save_window_position)

        if config.bp2_address:
            self.tab_bp2.set_configured(
                f"Appareil configure: {config.bp2_name or config.bp2_address}")
        if config.scale_address:
            self.tab_scale.set_configured(
                f"Balance configuree: {config.scale_name or config.scale_address}")
        if config.ft95_address:
            self.tab_ft95.set_configured(f"Thermometre configure: {config.ft95_address}")
        else:
            self.tab_ft95.set_configured("Detection automatique (par nom FT95/Beurer)")

        self._update_device_status()
        self.window.after(1000, self._poll_status)

    def _update_device_status(self) -> None:
        bp = read_status('bp2')
        if not bp:
            text, color = "Etat: connecteur inactif", 'gray'
        elif bp.get('connected'):
            text, color = "Etat: connecte a l'appareil", '#2a7a2a'
        else:
            text = f"Etat: {str(bp.get('state', '?')).lower()} (recherche/reconnexion en cours)"
            color = '#b06000'
        try:
            self.bp2_status_label.config(text=text, foreground=color)
        except tk.TclError:
            pass

        scale = read_status('scale')
        if not scale:
            text, color = "Etat: superviseur inactif", 'gray'
        elif scale.get('connected'):
            text, color = "Etat: connecte a la balance", '#2a7a2a'
        else:
            text = f"Etat: {str(scale.get('state', '?')).lower()}"
            color = '#b06000'
        try:
            self.scale_status_label.config(text=text, foreground=color)
        except tk.TclError:
            pass

        ft = read_status('ft95')
        if not ft:
            text, color = "Etat: superviseur inactif", 'gray'
        else:
            state = str(ft.get('state', '?')).lower()
            if state == 'libre':
                text = "Etat: thermometre libre - vous pouvez prendre une mesure"
                color = '#2a7a2a'
            elif state == 'connexion':
                text = "Etat: connexion au thermometre..."
                color = '#b06000'
            else:
                text = f"Etat: {state}"
                color = '#b06000'
        try:
            self.ft95_status_label.config(text=text, foreground=color)
        except tk.TclError:
            pass

    def _poll_status(self) -> None:
        if not self.window.winfo_exists():
            return
        self._update_device_status()
        self.window.after(1000, self._poll_status)

    def _check_queue(self) -> None:
        try:
            while True:
                action, data = self._ui_queue.get_nowait()
                if action == 'device_found':
                    tab, device = data
                    tab.add_device(device)
                elif action == 'scan_complete':
                    data.finish_scan()
        except queue.Empty:
            pass

        if self.window.winfo_exists():
            self.window.after(100, self._check_queue)

    def on_device_selected(self, tab: DeviceTab, device: BluetoothDevice) -> None:
        config = config_manager.config

        if tab is self.tab_bp2:
            config_manager.set_bp2_device(device.address, device.name)
            tab.set_configured(f"Appareil configure: {device.name}")
            if self.on_bp2_device:
                try:
                    self.on_bp2_device(device.address, device.name)
                    messagebox.showinfo("Succes",
                        f"Appareil {device.name} configure.\n\n"
                        "Reconnexion immediate en cours...")
                    return
                except Exception as e:
                    print(f"Erreur callback on_bp2_device: {e}")
            messagebox.showinfo("Succes",
                f"Appareil {device.name} configure avec succes !\n\n"
                "Il sera utilise au prochain demarrage de l'application.")

        elif tab is self.tab_scale:
            config_manager.set_scale_device(device.address, device.name)
            tab.set_configured(f"Balance configuree: {device.name}")
            messagebox.showinfo("Succes",
                f"Balance {device.name} configuree.\n\n"
                "La surveillance redemarre automatiquement.")

        elif tab is self.tab_ft95:
            config_manager.set_ft95_device(device.address, device.name)
            tab.set_configured(f"Thermometre configure: {device.name}")
            messagebox.showinfo("Succes",
                f"Thermometre {device.name} configure.\n\n"
                "Le prochain cycle utilisera cette adresse.")

    def _save(self) -> None:
        config_manager.update_config(
            auto_inject_doctolib=self.auto_inject_var.get(),
            play_sound_before_injection=self.play_sound_var.get(),
            block_keyboard_during_injection=self.block_keyboard_var.get(),
            auto_reconnect=self.auto_reconnect_var.get(),
            reconnect_delay_seconds=max(1.0, float(self.reconnect_delay_var.get() or 2.0)),
            max_reconnect_delay_seconds=max(2.0, float(self.max_reconnect_delay_var.get() or 5.0)),
            ft95_copy_clipboard=self.ft95_copy_var.get(),
            ft95_wait_first=max(5.0, float(self.ft95_wait_first_var.get() or 20.0)),
            ft95_collect=max(2.0, float(self.ft95_collect_var.get() or 8.0)),
            ft95_free=max(5.0, float(self.ft95_free_var.get() or 25.0)),
            show_floating_window=self.show_floating_window_var.get(),
            show_only_doctolib=self.show_only_doctolib_var.get(),
            save_window_position=self.save_window_position_var.get()
        )

        if self.on_save:
            try:
                self.on_save()
            except Exception as e:
                print(f"Erreur callback on_save: {e}")

        self.window.destroy()

    def _cancel(self) -> None:
        self.window.destroy()

    def show(self) -> None:
        self.window.wait_window()


def show_settings(parent: Optional[tk.Tk] = None,
                  on_save: Optional[Callable[[], None]] = None,
                  on_bp2_device: Optional[Callable[[str, str], None]] = None) -> None:
    dialog = SettingsDialog(parent, on_save, on_bp2_device)
    dialog.show()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    show_settings()
