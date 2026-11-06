"""Copie dans le presse-papiers reutilisable (Tkinter, sans dependance externe)."""
from __future__ import annotations


def copy_text(text: str, tk_root=None) -> bool:
    try:
        if tk_root is not None:
            tk_root.clipboard_clear()
            tk_root.clipboard_append(text)
            tk_root.update()
            return True

        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False
