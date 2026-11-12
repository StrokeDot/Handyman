"""Where things live, both when running from source and from the installed app."""
import os
import sys
from pathlib import Path

from version import APP_NAME, OLD_NAME


def resource_dir():
    """Read-only files shipped with the app (scene scripts, default templates)."""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def user_dir():
    """Writable per-user folder: templates, previews, logs."""
    base = os.environ.get('APPDATA') or str(Path.home() / '.config')
    d = Path(base) / APP_NAME
    old = Path(base) / OLD_NAME
    if not d.exists() and old.is_dir():           # the app was called Handyman: keep its books and logs
        try:
            old.rename(d)
        except OSError:
            import shutil
            shutil.copytree(old, d, dirs_exist_ok=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def remove_old_install():
    """After the update from Handyman: delete the old program folder and its shortcuts, which the
    installer could not remove while the old app was still closing. Books and settings live
    elsewhere and are not touched."""
    if not is_installed():
        return
    import shutil
    here = Path(sys.executable).resolve().parent
    local = os.environ.get('LOCALAPPDATA')
    if local:
        old = Path(local) / 'Programs' / OLD_NAME
        if old.is_dir() and old.resolve() != here and (old / f'{OLD_NAME}.exe').exists():
            shutil.rmtree(old, ignore_errors=True)
    roaming = os.environ.get('APPDATA')
    links = [Path(roaming) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / f'{OLD_NAME}.lnk'] if roaming else []
    links.append(Path.home() / 'Desktop' / f'{OLD_NAME}.lnk')
    for link in links:
        try:
            link.unlink()
        except OSError:
            pass


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
