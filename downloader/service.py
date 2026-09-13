"""Accès à yt-dlp : analyse, téléchargement et conversion éventuelle."""

from pathlib import Path
import sys

from yt_dlp import YoutubeDL

from .formats import Choice


def find_tool(name: str) -> str:
    """Localise un outil embarqué, ou son cache lors d'une exécution Python."""
    if getattr(sys, "frozen", False):
        # PyInstaller extrait l'exe dans ce dossier temporaire à chaque lancement.
        tools = Path(sys._MEIPASS) / "tools"
    else:
        tools = Path(__file__).resolve().parents[1] / ".tools"
    executable = tools / ("deno" if name == "deno" else "ffmpeg") / f"{name}.exe"
    if not executable.is_file():
        raise FileNotFoundError(
            f"{name} manque dans l'application. Utilisez un exe complet "
            "ou lancez build.py depuis les sources."
        )
    return str(executable)


def base_options(output: Path) -> dict:
    """Centralise les réglages communs ; aucun fichier de config utilisateur."""
    # Vérification unique au démarrage, avant de proposer les formats.
    ffmpeg = find_tool("ffmpeg")
    find_tool("ffprobe")
    deno = find_tool("deno")
    return {
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "ffmpeg_location": ffmpeg,
        "js_runtimes": {"deno": {"path": deno}},
        "paths": {"home": str(output)},
        "outtmpl": "%(title).150B [%(id)s] [%(format_id)s].%(ext)s",
        "windowsfilenames": True,
        "overwrites": False,
    }


def inspect_url(url: str, options: dict) -> dict:
    """Obtient les métadonnées d'un seul média sans le télécharger."""
    with YoutubeDL({**options, "quiet": True}) as client:
        info = client.extract_info(url, download=False)
    if not info or info.get("_type") in ("playlist", "multi_video"):
        raise ValueError(
            "Ce lien désigne une liste. Collez le lien d'une vidéo précise."
        )
    if info.get("is_live"):
        raise ValueError(
            "Les directs en cours ne sont pas pris en charge. Attendez la rediffusion."
        )
    return info


def download(url: str, choice: Choice, options: dict) -> None:
    """Télécharge avec progression et réanalyse le lien pour rafraîchir ses URL."""
    settings = {**options, "format": choice.selector}
    if choice.mp3:
        settings["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        # MKV accepte les combinaisons de codecs qui ne rentrent pas en MP4.
        settings["merge_output_format"] = "mp4/mkv"
    with YoutubeDL(settings) as client:
        if client.download([url]):
            raise RuntimeError("Le téléchargement n'a pas pu être terminé.")
