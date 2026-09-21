"""URL validation and format normalization, independent of the UI."""

from collections.abc import Mapping
from urllib.parse import urlsplit

from .models import Media, MediaFormat


def validate_url(value: str) -> str:
    """Normalize an HTTP(S) URL or raise a readable validation error."""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {'http', 'https'} and parsed.hostname
                 and not parsed.username and not parsed.password
                 and not any(char.isspace() or ord(char) < 32 for char in value))
        parsed.port  # Also reject malformed port numbers.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Enter a complete URL starting with https:// or http://.')
    return value


def media_from_info(info: Mapping, source_url: str) -> Media:
    """Keep every known, unprotected audio and video format."""
    raw_formats = info.get('formats') or ([info] if info.get('url') else [])
    formats = []
    for item in raw_formats:
        if (item.get('has_drm') or item.get('ext') in {'mhtml', 'jpg', 'png'}
                or item.get('protocol') == 'mhtml'
                or (item.get('vcodec') == 'none' and item.get('acodec') == 'none')):
            continue
        formats.append(MediaFormat(
            str(item.get('format_id') or 'original'), item.get('ext') or '?',
            item.get('vcodec'), item.get('acodec'), item.get('width'),
            item.get('height'), item.get('fps'), item.get('language'),
            item.get('dynamic_range'), item.get('abr') or item.get('tbr'),
            item.get('filesize') or item.get('filesize_approx'),
            not bool(item.get('filesize')) and bool(item.get('filesize_approx')),
        ))
    return Media(str(info['id']), source_url, info.get('title') or 'Untitled media',
                 info.get('extractor_key') or info.get('extractor') or 'Site',
                 tuple(formats), info.get('duration'), info.get('thumbnail'),
                 info.get('channel') or info.get('uploader') or info.get('creator'))


def format_size(value: int | float | None) -> str:
    """Format a byte count while distinguishing unknown sizes from zero."""
    if value is None:
        return 'Unknown'
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024
