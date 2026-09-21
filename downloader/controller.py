"""Application operations and session state, independent of NiceGUI."""

from pathlib import Path
from collections.abc import Callable
from threading import RLock
from typing import Protocol

from .models import (
    DownloadChoice,
    DownloadResult,
    Media,
    OperationPhase,
    OperationStatus,
)


class MediaService(Protocol):
    """Operations required by the controller from a media service."""

    def inspect(self, url: str) -> Media:
        """Analyze one media URL."""
        ...

    def download(
        self,
        media: Media,
        choice: DownloadChoice,
        destination: Path,
        report: Callable[[OperationStatus], None],
    ) -> DownloadResult:
        """Download one selected media format."""
        ...

    def request_stop(self) -> None:
        """Request cooperative shutdown of the current operation."""
        ...


class DownloadController:
    """Validate state transitions and expose read-only session properties."""

    def __init__(self, service: MediaService, destination: Path) -> None:
        """Inject the download service and initialize an empty session."""
        self._service = service
        self._destination = destination
        self._url = ""
        self._media: Media | None = None
        self._choice: DownloadChoice | None = None
        self._result: DownloadResult | None = None
        self._busy = False
        self._lock = RLock()
        self._status = OperationStatus()

    @property
    def url(self) -> str:
        """Current URL input, which may be incomplete."""
        with self._lock:
            return self._url

    @property
    def media(self) -> Media | None:
        """Last successfully analyzed media."""
        with self._lock:
            return self._media

    @property
    def choice(self) -> DownloadChoice | None:
        """Immutable selection belonging to the current media."""
        with self._lock:
            return self._choice

    @property
    def destination(self) -> Path:
        """Currently selected output folder."""
        with self._lock:
            return self._destination

    @property
    def result(self) -> DownloadResult | None:
        """Last confirmed output file."""
        with self._lock:
            return self._result

    @property
    def status(self) -> OperationStatus:
        """Current application status shared with the UI."""
        with self._lock:
            return self._status

    def _ensure_idle(self) -> None:
        """Reject changes while an operation is running."""
        with self._lock:
            if self._busy:
                raise ValueError("An operation is already in progress.")

    def _begin(self) -> None:
        """Reserve the session atomically to prevent concurrent operations."""
        with self._lock:
            self._ensure_idle()
            self._busy = True

    def change_url(self, value: str) -> None:
        """Update the URL and clear the media, selection and result together."""
        with self._lock:
            self._ensure_idle()
            if value != self._url:
                self._url = value
                self._reset_media()
                phase = (
                    OperationPhase.READY_TO_ANALYZE
                    if value.strip()
                    else OperationPhase.INITIAL
                )
                self._report(OperationStatus(phase))

    def _reset_media(self) -> None:
        """Clear the current media session while keeping user preferences."""
        with self._lock:
            self._media = None
            self._choice = None
            self._result = None

    def change_destination(self, path: Path) -> None:
        """Validate the folder before updating the destination."""
        with self._lock:
            self._ensure_idle()
            if not path.is_dir():
                raise ValueError("Choose an existing folder.")
            self._destination = path.resolve()

    def select(self, choice: DownloadChoice | None) -> None:
        """Accept only a selection from the current format catalog."""
        with self._lock:
            self._ensure_idle()
            if choice and (
                self._media is None
                or choice.primary not in self._media.formats
                or (choice.audio and choice.audio not in self._media.formats)
            ):
                raise ValueError(
                    "This selection does not belong to the analyzed media."
                )
            self._choice = choice
            phase = (
                OperationPhase.READY_TO_DOWNLOAD
                if choice
                else OperationPhase.NEEDS_SELECTION
            )
            self._report(OperationStatus(phase))

    def _report(self, status: OperationStatus) -> None:
        """Atomically replace the status snapshot shared with the UI."""
        with self._lock:
            self._status = status

    def analyze(self) -> None:
        """Analyze the URL and release the session even if analysis fails."""
        self._begin()
        self._reset_media()
        self._report(OperationStatus(OperationPhase.ANALYZING))
        try:
            media = self._service.inspect(self._url)
            with self._lock:
                self._media = media
            self._report(OperationStatus(OperationPhase.NEEDS_SELECTION))
        except Exception:
            self._report(OperationStatus(OperationPhase.ERROR, "Analysis failed."))
            raise
        finally:
            with self._lock:
                self._busy = False

    def download(self) -> None:
        """Reserve the session and download the selected formats."""
        self._begin()
        with self._lock:
            self._result = None
        try:
            with self._lock:
                media, choice, destination = (
                    self._media,
                    self._choice,
                    self._destination,
                )
            if not media or not choice:
                raise ValueError("Select a format first.")
            self._report(OperationStatus(OperationPhase.DOWNLOADING))
            result = self._service.download(media, choice, destination, self._report)
            with self._lock:
                self._result = result
            self._report(
                OperationStatus(
                    OperationPhase.COMPLETE, f"File ready: {result.path.name}", 1.0
                )
            )
        except Exception:
            self._report(OperationStatus(OperationPhase.ERROR, "Download failed."))
            raise
        finally:
            with self._lock:
                self._busy = False

    def request_stop(self) -> None:
        """Forward the shutdown request to the download service."""
        self._service.request_stop()
