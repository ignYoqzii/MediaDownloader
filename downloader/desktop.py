"""Local settings, clipboard monitoring and Windows folders."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import pyperclip

from .formats import validate_url


def data_directory() -> Path:
    """Return the user data folder independently of the executable location."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Media Downloader"


def downloads_directory() -> Path:
    """Resolve the Windows Downloads folder, including redirected locations."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(
                key, "{374DE290-123F-4565-9164-39C4925E467B}"
            )
            path = Path(os.path.expandvars(value))
            if path.is_dir():
                return path
    except (ImportError, OSError):
        pass
    fallback = Path.home() / "Downloads"
    return fallback if fallback.is_dir() else Path.home()


def load_destination() -> Path:
    """Load the last destination, falling back if the setting is invalid."""
    try:
        data = json.loads(
            (data_directory() / "settings.json").read_text(encoding="utf-8")
        )
        value = data.get("destination")
        if isinstance(value, str) and value and Path(value).is_dir():
            return Path(value)
    except (OSError, ValueError, AttributeError):
        pass
    return downloads_directory()


def save_destination(path: Path) -> None:
    """Replace settings atomically without storing URLs."""
    folder = data_directory()
    folder.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=folder, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"destination": str(path)}, stream, ensure_ascii=False)
        temporary.replace(folder / "settings.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def open_folder(path: Path) -> None:
    """Open the folder in Windows Explorer and let Windows report errors."""
    os.startfile(str(path))


class ClipboardListener:
    """Watch clipboard changes without keeping history or making network requests."""

    def __init__(self) -> None:
        """Initialize clipboard monitoring in the disabled state."""
        self._enabled = False
        self._previous: str | None = None
        self._candidate: str | None = None
        self._message = "Clipboard monitoring off"

    @property
    def enabled(self) -> bool:
        """Whether clipboard monitoring is enabled."""
        return self._enabled

    @property
    def candidate(self) -> str | None:
        """Latest valid URL still present in the clipboard."""
        return self._candidate

    @property
    def message(self) -> str:
        """Local status message; URL detection does not confirm downloadable media."""
        return self._message

    def set_enabled(self, enabled: bool) -> None:
        """Enable the next clipboard read or clear the current suggestion."""
        self._enabled = enabled
        self._previous = None
        self._candidate = None
        self._message = (
            "Waiting for a link..." if enabled else "Clipboard monitoring off"
        )

    def poll(self) -> bool:
        """Read the clipboard and report whether its contents changed."""
        if not self._enabled:
            return False
        try:
            text = pyperclip.paste()
        except (pyperclip.PyperclipException, OSError):
            self._message = "Clipboard temporarily unavailable"
            self._candidate = None
            self._previous = None
            return False
        if text == self._previous:
            return False
        self._previous = text
        try:
            self._candidate = validate_url(text)
            self._message = f"Link detected : {urlsplit(self._candidate).hostname}"
        except ValueError:
            self._candidate = None
            self._message = "Waiting for an HTTP(S) URL..."
        return True
