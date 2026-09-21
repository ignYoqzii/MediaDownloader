"""Native Windows entry point for Media Downloader."""

from multiprocessing import freeze_support

from nicegui import app

# Native settings must also run in the window subprocess.
app.native.window_args["resizable"] = False


def main() -> None:
    """Assemble the application and start the local server and native window."""
    import logging
    from logging.handlers import RotatingFileHandler

    from nicegui import ui

    from downloader.controller import DownloadController
    from downloader.desktop import data_directory, load_destination
    from downloader.service import YtDlpService, resource_root
    from downloader.ui import DownloaderView

    folder = data_directory()
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING,
        handlers=[
            RotatingFileHandler(
                folder / "application.log",
                maxBytes=1_000_000,
                backupCount=2,
                encoding="utf-8",
            )
        ],
    )
    controller = DownloadController(YtDlpService(), load_destination())

    @ui.page("/")
    def page() -> None:
        """Build the page within its NiceGUI context."""
        DownloaderView(controller)

    ui.run(
        native=True,
        reload=False,
        host="127.0.0.1",
        title="Media Downloader - By yoqzii",
        language="en-US",
        window_size=(1180, 900),
        favicon=resource_root() / "assets" / "icon.ico",
    )


if __name__ == "__main__":
    freeze_support()
    try:
        main()
    except Exception as error:
        import ctypes
        import logging

        logging.exception("Startup failed")
        ctypes.windll.user32.MessageBoxW(
            0, f"Unable to start Media Downloader.\n\n{error}", "Media Downloader", 0x10
        )
        raise SystemExit(1)
