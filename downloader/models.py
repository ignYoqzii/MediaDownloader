"""Immutable domain values exposed through read-only properties."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class StreamKind(StrEnum):
    """Known track composition of a source format."""

    VIDEO = 'Video only'
    AUDIO = 'Audio only'
    COMBINED = 'Video with audio'
    UNKNOWN = 'Unspecified'


@dataclass(frozen=True, slots=True)
class MediaFormat:
    """Source stream metadata; None means the site did not provide a value."""

    _id: str
    _extension: str
    _video_codec: str | None = None
    _audio_codec: str | None = None
    _width: int | None = None
    _height: int | None = None
    _fps: float | None = None
    _language: str | None = None
    _dynamic_range: str | None = None
    _bitrate: float | None = None
    _size: int | None = None
    _estimated: bool = False

    def __post_init__(self) -> None:
        """Reject empty identifiers and negative measurements."""
        if not self._id:
            raise ValueError('The format must have an identifier.')
        if any(value is not None and value < 0 for value in
               (self._width, self._height, self._fps, self._bitrate, self._size)):
            raise ValueError('Format measurements must be nonnegative.')

    @property
    def id(self) -> str:
        """Opaque identifier supplied by the extractor."""
        return self._id

    @property
    def extension(self) -> str:
        """Source stream container."""
        return self._extension

    @property
    def video_codec(self) -> str | None:
        """Video codec, 'none' when absent, or None when unknown."""
        return self._video_codec

    @property
    def audio_codec(self) -> str | None:
        """Audio codec, 'none' when absent, or None when unknown."""
        return self._audio_codec

    @property
    def width(self) -> int | None:
        """Width in pixels."""
        return self._width

    @property
    def height(self) -> int | None:
        """Height in pixels."""
        return self._height

    @property
    def fps(self) -> float | None:
        """Frame rate in frames per second."""
        return self._fps

    @property
    def language(self) -> str | None:
        """Language reported by the site."""
        return self._language

    @property
    def dynamic_range(self) -> str | None:
        """Dynamic range, such as SDR or HDR10."""
        return self._dynamic_range

    @property
    def bitrate(self) -> float | None:
        """Bitrate in kbit/s."""
        return self._bitrate

    @property
    def size(self) -> int | None:
        """Size in bytes, possibly estimated."""
        return self._size

    @property
    def estimated(self) -> bool:
        """Whether the reported size is an estimate."""
        return self._estimated

    @property
    def kind(self) -> StreamKind:
        """Distinguish missing tracks from unknown codec information."""
        video = self._video_codec not in (None, 'none')
        audio = self._audio_codec not in (None, 'none')
        if video and audio:
            return StreamKind.COMBINED
        if video and self._audio_codec == 'none':
            return StreamKind.VIDEO
        if audio and self._video_codec == 'none':
            return StreamKind.AUDIO
        return StreamKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class Media:
    """Analysis result with an immutable format catalog."""

    _id: str
    _source_url: str
    _title: str
    _site: str
    _formats: tuple[MediaFormat, ...]
    _duration: float | None = None
    _thumbnail: str | None = None
    _channel: str | None = None

    def __post_init__(self) -> None:
        """Ensure the format catalog is immutable and nonempty."""
        object.__setattr__(self, '_formats', tuple(self._formats))
        if not self._formats:
            raise ValueError('No downloadable audio or video formats are available.')

    @property
    def id(self) -> str:
        """Media identifier within its extractor."""
        return self._id

    @property
    def source_url(self) -> str:
        """URL to extract again before downloading."""
        return self._source_url

    @property
    def title(self) -> str:
        """Display title."""
        return self._title

    @property
    def site(self) -> str:
        """Name of the source extractor."""
        return self._site

    @property
    def formats(self) -> tuple[MediaFormat, ...]:
        """Immutable catalog in yt-dlp preference order."""
        return self._formats

    @property
    def duration(self) -> float | None:
        """Duration in seconds."""
        return self._duration

    @property
    def thumbnail(self) -> str | None:
        """Thumbnail URL, when available."""
        return self._thumbnail

    @property
    def channel(self) -> str | None:
        """Channel or creator reported by the extractor."""
        return self._channel


@dataclass(frozen=True, slots=True)
class DownloadChoice:
    """Exact source selection with an optional additional audio track."""

    _primary: MediaFormat
    _audio: MediaFormat | None = None
    _mp3: bool = False

    def __post_init__(self) -> None:
        """Reject incompatible combinations before calling yt-dlp."""
        if self._audio and (self._primary.kind != StreamKind.VIDEO
                            or self._audio.kind != StreamKind.AUDIO):
            raise ValueError('An audio track can only be added to a video without sound.')
        if self._mp3 and (self._audio or self._primary.audio_codec in (None, 'none')):
            raise ValueError('MP3 conversion requires a known audio track.')

    @property
    def primary(self) -> MediaFormat:
        """Selected primary format."""
        return self._primary

    @property
    def audio(self) -> MediaFormat | None:
        """Audio track added to a silent video."""
        return self._audio

    @property
    def mp3(self) -> bool:
        """Explicit conversion to MP3 at 192 kbit/s."""
        return self._mp3


class OperationPhase(StrEnum):
    """Stable phases used to coordinate the application state and UI."""

    INITIAL = 'initial'
    READY_TO_ANALYZE = 'ready_to_analyze'
    ANALYZING = 'analyzing'
    NEEDS_SELECTION = 'needs_selection'
    READY_TO_DOWNLOAD = 'ready_to_download'
    DOWNLOADING = 'downloading'
    PROCESSING = 'processing'
    COMPLETE = 'complete'
    ERROR = 'error'

    @property
    def default_message(self) -> str:
        """Message used when a status does not provide dynamic details."""
        return {
            self.INITIAL: 'Copy a URL to begin.',
            self.READY_TO_ANALYZE: 'Ready to analyze.',
            self.ANALYZING: 'Analyzing media and formats...',
            self.NEEDS_SELECTION: 'Select a format to download.',
            self.READY_TO_DOWNLOAD: 'Ready to download.',
            self.DOWNLOADING: 'Starting download...',
            self.PROCESSING: 'Processing the file - merging or converting...',
            self.COMPLETE: 'Download complete.',
            self.ERROR: 'Operation failed.',
        }[self]


@dataclass(frozen=True, slots=True)
class OperationStatus:
    """Immutable application status with optional transfer progress."""

    _phase: OperationPhase = OperationPhase.INITIAL
    _message: str | None = None
    _fraction: float | None = None

    @property
    def phase(self) -> OperationPhase:
        """Current stable phase of the application operation."""
        return self._phase

    @property
    def message(self) -> str:
        """Current phase and available measurements, ready for display."""
        return self._message or self._phase.default_message

    @property
    def fraction(self) -> float | None:
        """Progress of the current stream, or None when unknown."""
        return self._fraction


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Confirmed output file after post-processing."""

    _path: Path

    @property
    def path(self) -> Path:
        """Output path, which may have existed before the operation."""
        return self._path
