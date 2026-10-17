"""Where things live, both when running from source and from the installed app."""
import os
import sys
from pathlib import Path

from version import APP_NAME


def resource_dir():
    """Read-only files shipped with the app (scene scripts, default templates)."""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def user_dir():
    """Writable per-user folder: templates, previews, logs."""
    base = os.environ.get('APPDATA') or str(Path.home() / '.config')
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def books_dir():
    d = user_dir() / 'books'
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(name):
    d = user_dir() / 'cache' / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_installed():
    return bool(getattr(sys, 'frozen', False))
