"""Detection de la fenetre Doctolib (ouverte, visible et maximisee)."""


def is_doctolib_open_and_maximized() -> bool:
    try:
        from pywinauto import Desktop
        import win32gui
        import win32con

        windows = Desktop(backend="uia").windows()
        for win in windows:
            try:
                text = win.window_text()
                if not text or "doctolib" not in text.lower():
                    continue
                if not win.is_visible():
                    continue

                hwnd = win.handle
                placement = win32gui.GetWindowPlacement(hwnd)
                is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)

                if is_maximized:
                    return True
                return False
            except Exception as e:
                print(f"Erreur verification etat fenetre Doctolib: {e}")
                return True
        return False
    except Exception as e:
        print(f"Erreur verification Doctolib: {e}")
        return True
