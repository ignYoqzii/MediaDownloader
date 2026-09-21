"""Build dist/MediaDownloader.exe for Windows x64.

Install dependencies: python -m pip install -r requirements.txt
Then run python build.py. Downloaded tools are cached in .tools."""

from pathlib import Path
import subprocess
import sys
import tempfile
from shutil import copyfileobj
from urllib.request import urlretrieve
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / ".tools"


def prepare_tool(name: str, url: str, executables: tuple[str, ...]) -> None:
    """Keep the required executables, DLLs and licenses."""
    folder = TOOLS / name
    if not all((folder / executable).is_file() for executable in executables):
        print(f"Downloading {name} for the build...", flush=True)
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "tool.zip"
            urlretrieve(url, archive)
            with ZipFile(archive) as zipped:
                for entry in zipped.infolist():
                    filename = Path(entry.filename).name
                    if entry.is_dir() or not (
                        filename in executables
                        or filename.endswith(".dll")
                        or filename.upper().startswith(("LICENSE", "COPYING"))
                    ):
                        continue
                    # Use only the filename, discarding archive directory paths.
                    with zipped.open(entry) as source, (folder / filename).open(
                        "wb"
                    ) as target:
                        copyfileobj(source, target)
    for executable in executables:
        subprocess.run(
            [str(folder / executable), "--version" if name == "deno" else "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )


if __name__ == "__main__":
    prepare_tool(
        "ffmpeg",
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/"
        "ffmpeg-master-latest-win64-gpl-shared.zip",
        ("ffmpeg.exe", "ffprobe.exe"),
    )
    prepare_tool(
        "deno",
        "https://github.com/denoland/deno/releases/latest/download/"
        "deno-x86_64-pc-windows-msvc.zip",
        ("deno.exe",),
    )
    # Collect NiceGUI resources and yt-dlp dependencies.
    # Use PyInstaller from the current Python environment.
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--windowed",
                "--noconfirm",
                "--name",
                "MediaDownloader",
                "--collect-all",
                "yt_dlp_ejs",
                "--collect-data",
                "nicegui",
                "--icon",
                str(ROOT / "assets" / "icon.ico"),
                "--specpath",
                str(ROOT / "build"),
                "--add-data",
                f"{TOOLS};tools",
                "--add-data",
                f"{ROOT / 'assets'};assets",
                "main.py",
            ],
            cwd=ROOT,
        )
    )
