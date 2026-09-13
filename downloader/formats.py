"""Transforme les formats du site en choix lisibles, sans téléchargement."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Choice:
    """Un choix affiché et son sélecteur yt-dlp correspondant."""

    label: str
    selector: str
    mp3: bool = False


def choices_for(info: dict) -> list[Choice]:
    """Propose les qualités réellement disponibles et les pistes audio seules.

    yt-dlp ordonne les formats du moins bon au meilleur. Pour chaque hauteur,
    on garde le dernier : cela évite de demander à l'utilisateur un codec.
    Une vidéo sans son reçoit la meilleure piste audio lorsqu'elle existe.
    """
    formats = [f for f in info.get("formats", []) if not f.get("has_drm")]
    if not info.get("formats") and info.get("url") and not info.get("has_drm"):
        # Certains extracteurs génériques exposent un seul fichier sans codecs.
        return [Choice("Fichier original - format fourni par le site", "best")]
    audio = [
        f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"
    ]
    videos = {}
    for fmt in formats:
        # « none » signifie absent ; None signifie que le site ne précise pas le codec.
        if fmt.get("vcodec") != "none":
            videos[fmt.get("height") or 0] = fmt

    choices = []
    for height, fmt in sorted(videos.items(), reverse=True):
        selector = str(fmt["format_id"])
        silent = fmt.get("acodec") == "none"
        if silent and audio:
            selector += "+bestaudio"
        quality = f"{height}p" if height else "résolution inconnue"
        fps = f", {fmt['fps']:g} images/s" if fmt.get("fps") else ""
        sound = "sans son" if silent and not audio else "avec son"
        if fmt.get("acodec") is None:
            sound = "audio à vérifier (information non fournie par le site)"
        choices.append(Choice(f"Vidéo {quality}{fps} - {sound}", selector))

    # Une piste par conteneur/langue ; pas de réencodage pour ces choix.
    tracks = {}
    for fmt in audio:
        tracks[(fmt.get("ext", "audio"), fmt.get("language") or "")] = fmt
    for (ext, language), fmt in sorted(tracks.items()):
        suffix = f" - {language}" if language else ""
        choices.append(
            Choice(
                f"Audio {ext.upper()}{suffix} - qualité originale",
                str(fmt["format_id"]),
            )
        )
    if audio or any(f.get("acodec") != "none" for f in videos.values()):
        choices.append(
            Choice("Audio MP3 - conversion 192 kbit/s", "bestaudio/best", mp3=True)
        )
    return choices
