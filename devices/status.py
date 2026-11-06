"""Ecriture / lecture atomique des fichiers de statut par appareil."""
import json
import os
from datetime import datetime
from typing import Optional

from config_manager import get_status_path


def write_status(device: str, data: dict) -> None:
    data = dict(data)
    data['timestamp'] = datetime.now().isoformat()
    path = get_status_path(device)
    tmp = path.with_suffix('.json.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception as e:
        print(f"Erreur ecriture statut {device}: {e}")


def read_status(device: str) -> Optional[dict]:
    try:
        path = get_status_path(device)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None
