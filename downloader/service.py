"""yt-dlp integration for single-media downloads and progress reporting."""

from collections.abc import Callable, Iterator
import logging
from pathlib import Path
import sys
from threading import Event

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import DownloadCancelled

from .formats import format_size, media_from_info, validate_url
from .models import (
    DownloadChoice,
    DownloadResult,
    Media,
    OperationPhase,
    OperationStatus,
)


def resource_root() -> Path:
    """Return the extracted bundle resources or the source directory."""
    return (
        Path(sys._MEIPASS)
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )


def find_tool(name: str) -> str:
    """Locate a bundled tool and report missing executables."""
    root = resource_root() / ("tools" if getattr(sys, "frozen", False) else ".tools")
    executable = root / ("deno" if name == "deno" else "ffmpeg") / f"{name}.exe"
    if not executable.is_file():
        raise FileNotFoundError(
            f"{name} is missing. Run build.py or use a complete executable."
        )
    return str(executable)


class SingleMediaYoutubeDL(YoutubeDL):
    """Reject collections before yt-dlp starts processing their entries."""

    def process_ie_result(
        self, ie_result: dict, download: bool = True, extra_info: dict | None = None
    ) -> dict:
        """Allow yt-dlp to resolve redirects, but reject collections."""
        if ie_result.get("_type") in {"playlist", "multi_video"}:
            raise ValueError(
                "This link points to a playlist. Paste a link to a single media item."
            )
        if ie_result.get("is_live") or ie_result.get("live_status") in {
            "is_live",
            "is_upcoming",
        }:
            raise ValueError(
                "This media is live or scheduled. Wait until a recording is available."
            )
        return super().process_ie_result(ie_result, download, extra_info)


class FinalPathRecorder(PostProcessor):
    """Capture the output path after conversion, merging and the final move."""

    def __init__(self, client: YoutubeDL) -> None:
        """Attach the post-processor to the current operation."""
        super().__init__(client)
        self._path: Path | None = None

    @property
    def path(self) -> Path | None:
        """Output path reported by yt-dlp without reconstructing its filename."""
        return self._path

    def run(self, info: dict) -> tuple[list, dict]:
        """Record the moved file without modifying the result."""
        self._path = Path(info["filepath"])
        return [], info


def exact_selector(choice: DownloadChoice) -> Callable[[dict], Iterator[dict]]:
    """Build a format selector that treats identifiers as opaque values."""

    def select(context: dict) -> Iterator[dict]:
        """Select the exact streams without silently substituting formats."""
        selected = []
        for expected in (choice.primary, choice.audio):
            if expected is None:
                continue
            found = next(
                (
                    fmt
                    for fmt in context["formats"]
                    if str(fmt["format_id"]) == expected.id
                ),
                None,
            )
            if found is None or found.get("has_drm"):
                raise ValueError(
                    "The selected format is no longer available. Analyze the link again."
                )
            selected.append(found)
        if len(selected) == 1:
            yield selected[0]
        else:
            video, audio = selected
            yield {
                "format_id": f'{video["format_id"]}+{audio["format_id"]}',
                "ext": "mkv",
                "requested_formats": selected,
                "protocol": f'{video["protocol"]}+{audio["protocol"]}',
                "vcodec": video.get("vcodec"),
                "acodec": audio.get("acodec"),
            }

    return select


class YtDlpService:
    """Manage download engine options independently of NiceGUI."""

    def __init__(self) -> None:
        """Create the cooperative shutdown signal."""
        self._stop = Event()

    def request_stop(self) -> None:
        """Request cancellation at the next hook without forcibly stopping FFmpeg."""
        self._stop.set()

    def _options(self) -> dict:
        """Prepare tools and fresh engine options for each operation."""
        find_tool("ffprobe")
        return {
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "logger": logging.getLogger("media_downloader.ytdlp"),
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "ffmpeg_location": find_tool("ffmpeg"),
            "js_runtimes": {"deno": {"path": find_tool("deno")}},
            "windowsfilenames": True,
            "overwrites": False,
            "ignoreerrors": False,
        }

    def inspect(self, url: str) -> Media:
        """Analyze a single media URL without downloading its streams."""
        url = validate_url(url)
        with SingleMediaYoutubeDL(self._options()) as client:
            info = client.extract_info(url, download=False)
            if not info:
                raise ValueError("No media found at this address.")
            return media_from_info(info, url)

    def download(
        self,
        media: Media,
        choice: DownloadChoice,
        destination: Path,
        report: Callable[[OperationStatus], None],
    ) -> DownloadResult:
        """Re-extract metadata, validate the selection and produce the output file."""
        options = self._options()

        def progress(data: dict) -> None:
            """Convert transfer hooks into progress snapshots with bounded fractions."""
            if self._stop.is_set():
                raise DownloadCancelled("Cancellation requested.")
            if data["status"] == "finished":
                report(
                    OperationStatus(
                        OperationPhase.PROCESSING,
                        "Stream received - preparing the file...",
                    )
                )
                return
            if data["status"] != "downloading":
                return
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            received = data.get("downloaded_bytes") or 0
            fraction = min(received / total, 1.0) if total else None
            stream = data.get("info_dict", {}).get("format_id", "")
            parts = [f"Stream {stream} | {format_size(received)}"]
            if total:
                parts.append(
                    f'/ {"≈ " if not data.get("total_bytes") else ""}{format_size(total)}'
                )
            if data.get("speed"):
                parts.append(f'| {format_size(data["speed"])}/s')
            if data.get("eta") is not None:
                parts.append(f'| {int(data["eta"])} s remaining')
            report(
                OperationStatus(OperationPhase.DOWNLOADING, " ".join(parts), fraction)
            )

        def processing(data: dict) -> None:
            """Report post-processing without inventing an FFmpeg percentage."""
            del data
            report(OperationStatus(OperationPhase.PROCESSING))

        suffix = " [mp3]" if choice.mp3 else ""
        options.update(
            {
                "format": exact_selector(choice),
                "paths": {"home": str(destination)},
                "outtmpl": f"%(title).150B [%(id)s] [%(format_id)s]{suffix}.%(ext)s",
                "progress_hooks": [progress],
                "postprocessor_hooks": [processing],
                "merge_output_format": "mkv",
            }
        )
        if choice.mp3:
            options.update(
                {
                    "final_ext": "mp3",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
        with SingleMediaYoutubeDL(options) as client:
            report(
                OperationStatus(
                    OperationPhase.DOWNLOADING, "Checking media and formats..."
                )
            )
            info = client.extract_info(media.source_url, download=False)
            current = media_from_info(info, media.source_url)
            if (current.id, current.site) != (media.id, media.site):
                raise ValueError(
                    "The link now points to different media. Analyze it again."
                )
            for expected in (choice.primary, choice.audio):
                if expected is None:
                    continue
                actual = next(
                    (fmt for fmt in current.formats if fmt.id == expected.id), None
                )
                # Sizes and signed URLs may change; the selected format properties must match.
                fields = (
                    "extension",
                    "video_codec",
                    "audio_codec",
                    "width",
                    "height",
                    "fps",
                    "language",
                    "dynamic_range",
                )
                if actual is None or any(
                    getattr(actual, key) != getattr(expected, key) for key in fields
                ):
                    raise ValueError(
                        "The selected format has changed. Analyze the link again."
                    )
            if self._stop.is_set():
                raise DownloadCancelled("Cancellation requested.")
            recorder = FinalPathRecorder(client)
            client.add_post_processor(recorder, when="after_move")
            client.process_video_result(info, download=True)
            path = recorder.path
            if path is None or not path.is_file():
                raise RuntimeError(
                    "The download engine did not confirm the output file."
                )
            return DownloadResult(path)
