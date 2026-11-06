"""Gestionnaire de configuration unifie pour le widget ConstantesCab."""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict


APP_NAME = "ConstantesCab"


def get_data_dir() -> Path:
    user_docs = Path(os.environ.get('USERPROFILE', os.path.expanduser('~'))) / 'Documents' / APP_NAME
    user_docs.mkdir(parents=True, exist_ok=True)
    return user_docs


def get_config_file() -> Path:
    return get_data_dir() / 'config.json'


def get_status_path(device: str) -> Path:
    return get_data_dir() / f'status_{device}.json'


@dataclass
class AppConfig:
    bp2_address: Optional[str] = None
    bp2_name: Optional[str] = None

    scale_address: Optional[str] = None
    scale_name: Optional[str] = None

    ft95_address: Optional[str] = None
    ft95_copy_clipboard: bool = True
    ft95_wait_first: float = 20.0
    ft95_collect: float = 8.0
    ft95_free: float = 25.0

    auto_inject_doctolib: bool = True
    play_sound_before_injection: bool = True
    block_keyboard_during_injection: bool = True
    injection_delay_seconds: float = 2.0

    show_floating_window: bool = True
    show_only_doctolib: bool = True
    save_window_position: bool = False
    main_window_position: Optional[Dict[str, int]] = None

    auto_reconnect: bool = True
    reconnect_delay_seconds: float = 2.0
    max_reconnect_delay_seconds: float = 30.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)


class ConfigManager:
    _instance: Optional['ConfigManager'] = None

    def __new__(cls) -> 'ConfigManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = AppConfig()
            cls._instance._config_file = get_config_file()
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        if self._config_file.exists():
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._config = AppConfig.from_dict(data)
                print(f"Configuration chargee depuis: {self._config_file}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                print(f"Erreur lors du chargement de la configuration: {e}")
                self._config = AppConfig()
                self.save_config()
        else:
            print(f"Nouveau fichier de configuration cree: {self._config_file}")
            self.save_config()

    def save_config(self) -> None:
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erreur lors de la sauvegarde de la configuration: {e}")

    @property
    def config(self) -> AppConfig:
        return self._config

    def update_config(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self.save_config()

    def set_bp2_device(self, address: str, name: Optional[str] = None) -> None:
        self._config.bp2_address = address
        self._config.bp2_name = name
        self.save_config()

    def set_scale_device(self, address: str, name: Optional[str] = None) -> None:
        self._config.scale_address = address
        self._config.scale_name = name
        self.save_config()

    def set_ft95_device(self, address: Optional[str], name: Optional[str] = None) -> None:
        self._config.ft95_address = address
        self.save_config()


config_manager = ConfigManager()
