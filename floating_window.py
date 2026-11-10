"""Fenetre flottante unique ConstantesCab : tension, poids et temperature sur une bande Doctolib.

Style du widget tension : fond #004080, contour #345677, bords arrondis demi-cercles.
Affichage conditionnel possible : uniquement si Doctolib est ouvert et maximise.
"""
import atexit
import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config_manager import config_manager, get_status_path
from doctolib_detect import is_doctolib_open_and_maximized


class CompactProgressBar:
    """Barre de progression style Doctolib."""

    def __init__(self, parent: tk.Widget, width: int = 100, height: int = 12, bg_color: str = '#004080'):
        self.canvas = tk.Canvas(parent, width=width, height=height,
                                bg=bg_color, highlightthickness=0)
        self.width = width
        self.height = height
        self.bg_color = bg_color
        self.current_value = 0.0
        self.target_value = 0.0
        self._animation_id: Optional[int] = None

        self.canvas.create_rectangle(0, 0, width, height, fill=bg_color, outline='')

        self.fill_rect = self.canvas.create_rectangle(
            1, 1, 1, height - 1, fill='white', outline='', stipple='gray50'
        )

    def set_value(self, value: float) -> None:
        self.target_value = max(0.0, min(100.0, value))
        self._animate()

    def _animate(self) -> None:
        if self._animation_id:
            self.canvas.after_cancel(self._animation_id)

        diff = self.target_value - self.current_value

        if abs(diff) < 0.5:
            self.current_value = self.target_value
            self._draw()
            return

        step = diff * 0.3
        self.current_value += step
        self._draw()

        self._animation_id = self.canvas.after(16, self._animate)

    def _draw(self) -> None:
        fill_width = 1 + (self.current_value / 100.0) * (self.width - 2)
        self.canvas.coords(self.fill_rect, 1, 1, fill_width, self.height - 1)

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)


class FloatingWindowCompact:
    """Fenetre flottante unifiee avec bords arrondis."""

    DOCTO_BLUE = '#004080'
    DOCTO_BORDER = '#345677'
    WHITE = '#ffffff'
    GREY = '#aaaaaa'
    MUTED = '#8fb8d8'

    def __init__(self, on_settings: Optional[Callable[[], None]] = None):
        self.on_settings = on_settings
        self._lock_file = get_status_path('_window').with_name('constantescab.lock')
        self._acquire_lock()

        self.save_position_enabled = config_manager.config.save_window_position
        self.saved_position = config_manager.config.main_window_position
        self.visible = True
        self.user_hidden = False
        self.last_doctolib_state = None

        self._doctolib_ok = True
        self._doctolib_check_event = threading.Event()
        self._doctolib_thread = threading.Thread(
            target=self._doctolib_check_worker, daemon=True, name="DoctolibCheck"
        )

        self.root = tk.Tk()
        self.root.title("ConstantesCab")
        self.root.geometry("200x28")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.98)
        self.root.configure(bg=self.DOCTO_BLUE)

        if self.save_position_enabled and self.saved_position:
            x = self.saved_position.get('x')
            y = self.saved_position.get('y')
            if x is not None and y is not None:
                self.root.geometry(f"+{x}+{y}")
            else:
                screen_width = self.root.winfo_screenwidth()
                self.root.geometry(f"+{screen_width - 640}+8")
        else:
            screen_width = self.root.winfo_screenwidth()
            self.root.geometry(f"+{screen_width - 640}+8")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._drag_data = {"x": 0, "y": 0}

        self._create_ui()
        self._setup_drag()
        self._resize_to_content()
        self._start_update_loop()
        self._doctolib_thread.start()
        self._start_doctolib_check()

        if config_manager.config.show_only_doctolib:
            doctolib_ok = is_doctolib_open_and_maximized()
            self.last_doctolib_state = doctolib_ok
            if not doctolib_ok:
                self.hide_window(save_state=False)

        atexit.register(self._on_close)
        atexit.register(self._release_lock)

    def _save_current_position(self) -> None:
        try:
            geom = self.root.geometry().split('+')
            if len(geom) >= 3:
                x = int(geom[1])
                y = int(geom[2])
                config_manager.update_config(
                    main_window_position={'x': x, 'y': y},
                    save_window_position=True
                )
                self.save_position_enabled = True

                old_color = self.save_pos_btn['fg']
                self.save_pos_btn.config(fg='#4ecdc4')
                self.root.after(1000, lambda: self.save_pos_btn.config(fg=old_color))
        except Exception as e:
            print(f"Erreur enregistrement position: {e}")

    def _doctolib_check_worker(self) -> None:
        while not self._doctolib_check_event.is_set():
            try:
                self._doctolib_ok = is_doctolib_open_and_maximized()
            except Exception:
                self._doctolib_ok = True
            self._doctolib_check_event.wait(2.0)

    def _on_close(self) -> None:
        try:
            if self.save_position_enabled:
                self._save_current_position()
            self.root.destroy()
        except Exception:
            pass

    def _acquire_lock(self) -> None:
        try:
            if self._lock_file.exists():
                with open(self._lock_file, 'r') as f:
                    pid = int(f.read().strip())
                import os
                try:
                    os.kill(pid, 0)
                    print("Une instance est deja en cours d'execution")
                    exit(0)
                except OSError:
                    pass

            import os
            with open(self._lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print(f"Erreur lock: {e}")

    def _release_lock(self) -> None:
        try:
            if self._lock_file.exists():
                self._lock_file.unlink()
        except Exception:
            pass

    def hide_window(self, save_state: bool = True) -> None:
        if save_state:
            self.user_hidden = True
        if self.visible:
            self.visible = False
            self.root.withdraw()

    def show_window(self) -> None:
        if not self.visible:
            self.visible = True
            self.root.deiconify()

    BAR_HEIGHT = 28
    BAR_RADIUS = 14

    def _draw_rounded_bg(self, width: int) -> None:
        """Redessine le fond arrondi pour la largeur demandee.

        Ne touche jamais a la frame de contenu : seuls les items de fond,
        suivis dans self._bg_ids, sont supprimes et redessines, puis passes
        sous la frame (qui reste au-dessus).
        """
        height = self.BAR_HEIGHT
        radius = self.BAR_RADIUS
        canvas = self.rounded_canvas

        for sid in getattr(self, '_bg_ids', []):
            canvas.delete(sid)

        self._bg_ids = []

        self._bg_ids.append(canvas.create_rectangle(
            radius, 0, width - radius, height,
            fill=self.DOCTO_BLUE, outline=''))
        self._bg_ids.append(canvas.create_arc(
            0, 0, radius * 2, height, start=90, extent=180,
            fill=self.DOCTO_BLUE, outline=''))
        self._bg_ids.append(canvas.create_arc(
            width - radius * 2, 0, width, height, start=270, extent=180,
            fill=self.DOCTO_BLUE, outline=''))

        self._bg_ids.append(canvas.create_line(
            radius, 0, width - radius, 0,
            fill=self.DOCTO_BORDER, width=2))
        self._bg_ids.append(canvas.create_line(
            radius, height, width - radius, height,
            fill=self.DOCTO_BORDER, width=2))
        self._bg_ids.append(canvas.create_arc(
            0, 0, radius * 2, height, start=90, extent=180,
            fill='', outline=self.DOCTO_BORDER, width=2, style='arc'))
        self._bg_ids.append(canvas.create_arc(
            width - radius * 2, 0, width, height, start=270, extent=180,
            fill='', outline=self.DOCTO_BORDER, width=2, style='arc'))

        for item in reversed(self._bg_ids):
            canvas.tag_lower(item)

        canvas.config(width=width, height=height)

    def _resize_to_content(self) -> None:
        """Ajuste la largeur de la fenetre au contenu reel (polices variables selon le PC)."""
        try:
            self.content_frame.update_idletasks()
            content_width = self.content_frame.winfo_reqwidth()
            total = content_width + 2 * self.BAR_RADIUS + 8
            if total < 200:
                total = 200

            if total != getattr(self, '_bar_width', None):
                self._bar_width = total
                self._draw_rounded_bg(total)
                self.root.geometry(f"{total}x{self.BAR_HEIGHT}")
        except Exception as e:
            print(f"Erreur redimensionnement: {e}")

    def _create_ui(self) -> None:
        main_frame = tk.Frame(self.root, bg=self.root['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self._bg_ids = []
        self.rounded_canvas = tk.Canvas(main_frame, width=200, height=self.BAR_HEIGHT,
                                        bg=self.root['bg'], highlightthickness=0)
        self.rounded_canvas.pack(fill=tk.BOTH, expand=True)

        self.content_frame = tk.Frame(self.rounded_canvas, bg=self.DOCTO_BLUE)
        self.content_frame.place(relx=0.5, rely=0.5, anchor='center')

        self._draw_rounded_bg(200)
        content_frame = self.content_frame

        self.logo_label = tk.Label(
            content_frame, text="\U0001FA7A", font=('Segoe UI', 10),
            fg=self.WHITE, bg=self.DOCTO_BLUE, cursor='hand2'
        )
        self.logo_label.pack(side=tk.LEFT, padx=(8, 4))
        self.logo_label.bind('<Button-1>', lambda e: self._open_settings())
        self._create_tooltip(self.logo_label, "Parametres ConstantesCab")

        self.status_canvas = tk.Canvas(content_frame, width=6, height=6,
                                       bg=self.DOCTO_BLUE, highlightthickness=0)
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self.status_circle = self.status_canvas.create_oval(
            0, 0, 6, 6, fill='#ff6b6b', outline=''
        )

        self.progress = CompactProgressBar(content_frame, width=70, height=10, bg_color=self.DOCTO_BLUE)
        self.progress.pack(side=tk.LEFT, padx=(0, 6))

        self.bp_label = tk.Label(
            content_frame, text="---/---", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE, width=9
        )
        self.bp_label.pack(side=tk.LEFT, padx=(0, 2))

        self.hr_label = tk.Label(
            content_frame, text="--", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE, width=3
        )
        self.hr_label.pack(side=tk.LEFT, padx=(0, 0))

        self.bpm_label = tk.Label(
            content_frame, text="bpm", font=('Segoe UI', 8),
            fg=self.GREY, bg=self.DOCTO_BLUE
        )
        self.bpm_label.pack(side=tk.LEFT, padx=(0, 4))

        self.bp_time_label = tk.Label(
            content_frame, text="", font=('Segoe UI', 8),
            fg=self.MUTED, bg=self.DOCTO_BLUE
        )
        self.bp_time_label.pack(side=tk.LEFT, padx=(0, 8))

        self.sep1 = tk.Label(content_frame, text="|", font=('Segoe UI', 9),
                             fg=self.DOCTO_BORDER, bg=self.DOCTO_BLUE)
        self.sep1.pack(side=tk.LEFT, padx=(0, 8))

        self.scale_icon = tk.Label(
            content_frame, text="\u2696", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE
        )
        self.scale_icon.pack(side=tk.LEFT, padx=(0, 3))

        self.weight_label = tk.Label(
            content_frame, text="--.- kg", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE, width=8
        )
        self.weight_label.pack(side=tk.LEFT, padx=(0, 2))

        self.weight_time_label = tk.Label(
            content_frame, text="", font=('Segoe UI', 8),
            fg=self.MUTED, bg=self.DOCTO_BLUE
        )
        self.weight_time_label.pack(side=tk.LEFT, padx=(0, 8))

        self.sep2 = tk.Label(content_frame, text="|", font=('Segoe UI', 9),
                             fg=self.DOCTO_BORDER, bg=self.DOCTO_BLUE)
        self.sep2.pack(side=tk.LEFT, padx=(0, 8))

        self.temp_icon = tk.Label(
            content_frame, text="\U0001F321", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE
        )
        self.temp_icon.pack(side=tk.LEFT, padx=(0, 3))

        self.temp_label = tk.Label(
            content_frame, text="--.- °C", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE, width=7
        )
        self.temp_label.pack(side=tk.LEFT, padx=(0, 2))

        self.temp_time_label = tk.Label(
            content_frame, text="", font=('Segoe UI', 8),
            fg=self.MUTED, bg=self.DOCTO_BLUE
        )
        self.temp_time_label.pack(side=tk.LEFT, padx=(0, 8))

        self.battery_label = tk.Label(
            content_frame, text="--%", font=('Segoe UI', 9),
            fg=self.WHITE, bg=self.DOCTO_BLUE, width=4
        )
        self.battery_label.pack(side=tk.LEFT, padx=(0, 6))

        self.save_pos_btn = tk.Label(
            content_frame, text="\U0001F4BE", font=('Segoe UI', 9),
            fg=self.GREY, bg=self.DOCTO_BLUE, cursor='hand2'
        )
        self.save_pos_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.save_pos_btn.bind('<Button-1>', lambda e: self._save_current_position())
        self._create_tooltip(self.save_pos_btn, "Enregistrer la position actuelle")

        self.close_btn = tk.Label(
            content_frame, text="\u2715", font=('Segoe UI', 9),
            fg=self.GREY, bg=self.DOCTO_BLUE, cursor='hand2'
        )
        self.close_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.close_btn.bind('<Button-1>', lambda e: self._close_window())

    def _create_tooltip(self, widget: tk.Widget, text: str) -> None:
        def enter(event):
            self.tooltip = tk.Toplevel(self.root)
            self.tooltip.wm_overrideredirect(True)
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + 25
            self.tooltip.wm_geometry(f"+{x}+{y}")
            tk.Label(self.tooltip, text=text, bg='#333333', fg='white',
                     font=('Segoe UI', 9), padx=5, pady=2).pack()

        def leave(event):
            if hasattr(self, 'tooltip'):
                self.tooltip.destroy()

        widget.bind('<Enter>', enter)
        widget.bind('<Leave>', leave)

    def _setup_drag(self) -> None:
        def on_press(event):
            self._drag_data["x"] = event.x_root - self.root.winfo_x()
            self._drag_data["y"] = event.y_root - self.root.winfo_y()

        def on_drag(event):
            x = event.x_root - self._drag_data["x"]
            y = event.y_root - self._drag_data["y"]
            self.root.geometry(f"+{x}+{y}")

        self.root.bind("<ButtonPress-1>", on_press)
        self.root.bind("<B1-Motion>", on_drag)

    def _open_settings(self) -> None:
        if self.on_settings:
            try:
                self.on_settings()
            except Exception as e:
                print(f"Erreur ouverture parametres: {e}")

    def _close_window(self) -> None:
        self._release_lock()
        self.root.destroy()

    def _read_status(self, device: str) -> Optional[dict]:
        try:
            path = get_status_path(device)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    @staticmethod
    def _fmt_time(iso: Optional[str]) -> str:
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(iso).strftime("%H:%M")
        except (ValueError, TypeError):
            return ""

    def _update_display(self) -> None:
        self._resize_to_content()

        bp = self._read_status('bp2') or {}
        scale = self._read_status('scale') or {}
        ft = self._read_status('ft95') or {}

        connected = bp.get('connected', False)
        if connected:
            self.status_canvas.itemconfig(self.status_circle, fill='#4ecdc4')
        else:
            self.status_canvas.itemconfig(self.status_circle, fill='#ff6b6b')

        is_measuring = bp.get('is_measuring', False)
        pressure = bp.get('pressure', 0.0)
        if is_measuring:
            self.progress.set_value(min(100.0, (pressure / 200.0) * 100.0))
        else:
            self.progress.set_value(0.0)

        last_result = bp.get('last_result') or {}
        if is_measuring:
            self.bp_label.config(text=f"{int(pressure)}")
        elif last_result.get('sys'):
            self.bp_label.config(text=f"{last_result.get('sys')}/{last_result.get('dia')}")
        else:
            self.bp_label.config(text="---/---")

        if last_result.get('pr') and not is_measuring:
            self.hr_label.config(text=f"{last_result['pr']}", fg=self.WHITE)
            self.bpm_label.config(fg=self.GREY)
        else:
            self.hr_label.config(text="--", fg='#888888')
            self.bpm_label.config(fg='#666666')

        self.bp_time_label.config(text=self._fmt_time(last_result.get('measured_at')))

        battery = bp.get('battery', 0)
        if battery > 0:
            self.battery_label.config(text=f"{battery}%", fg=self.WHITE)
        else:
            self.battery_label.config(text="--%", fg='#888888')

        weight = scale.get('weight')
        if weight is not None:
            self.weight_label.config(text=f"{weight:.1f} kg", fg=self.WHITE)
        else:
            self.weight_label.config(text="--.- kg", fg='#888888')
        self.weight_time_label.config(text=self._fmt_time(scale.get('measured_at')))

        temp = ft.get('temperature_c')
        if temp is not None:
            color = '#ff9f43' if temp >= 38.0 else self.WHITE
            self.temp_label.config(text=f"{temp:.1f} °C", fg=color)
        else:
            self.temp_label.config(text="--.- °C", fg='#888888')
        self.temp_time_label.config(text=self._fmt_time(ft.get('measured_at')))

    def _start_update_loop(self) -> None:
        def update():
            self._update_display()
            self.root.after(100, update)

        self.root.after(100, update)

    def _start_doctolib_check(self) -> None:
        def check():
            try:
                if not config_manager.config.show_floating_window:
                    if self.visible:
                        self.hide_window(save_state=False)
                else:
                    show_only_doctolib = config_manager.config.show_only_doctolib

                    if show_only_doctolib and not self.user_hidden:
                        doctolib_ok = self._doctolib_ok

                        if doctolib_ok and not self.visible:
                            self.show_window()
                        elif not doctolib_ok and self.visible:
                            self.hide_window(save_state=False)

                        if doctolib_ok != self.last_doctolib_state:
                            self.last_doctolib_state = doctolib_ok
                    elif not show_only_doctolib and not self.user_hidden and not self.visible:
                        self.show_window()
            except Exception:
                pass

            self.root.after(1000, check)

        self.root.after(1000, check)

    def run(self) -> None:
        self.root.mainloop()


def main():
    window = FloatingWindowCompact()
    window.run()


if __name__ == "__main__":
    main()
