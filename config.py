import json
import os

CONFIG_DIR = os.path.expanduser("~/.pyenvy")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "managed_venvs": [],
    "scan_directories": [os.path.expanduser("~")],
    "scan_max_depth": 3,
    "default_venv_location": os.path.expanduser("~/Envs"),
    "window_geometry": "1000x650",
    "sash_position": 250,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            merged = {**DEFAULT_CONFIG, **data}
            return merged
        except (json.JSONDecodeError, IOError):
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def add_managed_venv(config, venv_path):
    path = os.path.abspath(venv_path)
    if path not in config["managed_venvs"]:
        config["managed_venvs"].append(path)
    return config


def remove_managed_venv(config, venv_path):
    path = os.path.abspath(venv_path)
    config["managed_venvs"] = [p for p in config["managed_venvs"] if p != path]
    return config
