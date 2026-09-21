"""NiceGUI desktop view with persistent sections and standard components."""

import logging
from collections.abc import Callable
from pathlib import Path

from nicegui import app, run, ui

from .controller import DownloadController
from .desktop import ClipboardListener, open_folder, save_destination
from .formats import format_size
from .models import DownloadChoice, OperationPhase, StreamKind


def describe_choice(choice: DownloadChoice) -> dict[str, str]:
    """Describe a download using short labels and separate table columns."""
    fmt = choice.primary
    if choice.mp3:
        return {'format': 'MP3 audio', 'quality': '192 kbps (converted)',
                'audio': fmt.language or 'Included', 'size': 'After conversion'}
    quality = []
    if fmt.height:
        quality.append(f'{fmt.height}p')
    if fmt.fps:
        quality.append(f'{fmt.fps:g} fps')
    if fmt.kind == StreamKind.AUDIO and fmt.bitrate:
        quality.append(f'{fmt.bitrate:g} kbps')
    if fmt.dynamic_range and fmt.dynamic_range != 'SDR':
        quality.append(fmt.dynamic_range)
    kind = 'audio' if fmt.kind == StreamKind.AUDIO else 'video' if fmt.kind in {
        StreamKind.VIDEO, StreamKind.COMBINED} else 'media'
    audio = 'Included' if fmt.audio_codec not in (None, 'none') else 'None' if fmt.audio_codec == 'none' else 'Unknown'
    if choice.audio:
        audio = 'Added (MKV)'
    language = choice.audio.language if choice.audio else fmt.language
    if language:
        audio += f' ({language})'
    size = ('~ ' if fmt.estimated else '') + format_size(fmt.size)
    if choice.audio:
        size = '~ ' + format_size(fmt.size + choice.audio.size) if fmt.size and choice.audio.size else 'Unknown'
    return {'format': f'{fmt.extension.upper()} {kind}',
            'quality': ', '.join(quality) or 'Original', 'audio': audio, 'size': size}


class DownloaderView:
    """Handle user actions through the controller and read-only domain values."""

    def __init__(self, controller: DownloadController) -> None:
        """Build the five persistent sections of the window."""
        self._controller = controller
        self._listener = ClipboardListener()
        self._working = False
        self._ready = False
        self._focused = False
        self._updating = False
        self._options: dict[str, DownloadChoice] = {}
        ui.colors(primary='#1769c9')
        ui.query('.nicegui-content').classes('p-0 gap-0')
        # Use NiceGUI layouts for sizing. Only the background and table
        # need custom CSS; no custom HTML or Vue components are required.
        ui.add_css('''
            body { background: #f7f8fa; color: #20242c; }
            .format-table .q-table__middle { flex: 1; min-height: 0; overflow: auto; }
            .format-table tbody tr.selected { background: #e8f0fc; }
            .format-table td { white-space: normal; }
            .format-table thead th { position: sticky; top: 0; background: white; z-index: 1; }
        ''')
        with ui.column().classes('w-full h-screen p-4 gap-3 flex-nowrap'):
            self._build_url_bar()
            self._build_preview()
            self._build_formats()
            self._build_actions()
            self._build_status()
        ui.timer(0.5, self._poll_clipboard)
        app.on_shutdown(controller.request_stop)

    @property
    def can_edit(self) -> bool:
        """Allow changes when no UI operation is running."""
        return not self._working

    @property
    def media_ready(self) -> bool:
        """Display media details once the format catalog is ready."""
        return self._ready

    @property
    def can_filter(self) -> bool:
        """Enable filters only after analysis completes."""
        return self._ready and self.can_edit

    @property
    def can_download(self) -> bool:
        """Enable downloading when a valid format is selected."""
        return self.can_filter and self._controller.choice is not None

    @property
    def has_candidate(self) -> bool:
        """Whether the clipboard contains a URL different from the current input."""
        return bool(self._listener.candidate and self._listener.candidate != self._controller.url)

    @property
    def selection_summary(self) -> str:
        """Describe the expected output separately from the source format label."""
        choice = self._controller.choice
        if not choice:
            return 'No format selected'
        if choice.mp3:
            return 'MP3 audio - 192 kbps'
        if choice.audio:
            quality = f'{choice.primary.height}p' if choice.primary.height else 'Original'
            return f'{quality} video with audio (MKV)'
        row = describe_choice(choice)
        return f'{row["format"]} - {row["quality"]}'

    def _build_url_bar(self) -> None:
        """Place the URL input, clipboard switch and analyze button on one row."""
        with ui.column().classes('w-full gap-0 shrink-0'):
            with ui.row().classes('w-full items-center gap-3 flex-nowrap'):
                self._url = ui.input('Media URL', placeholder='https://...',
                    on_change=self._url_changed).props('outlined dense').classes('flex-1 min-w-0')
                self._url.bind_enabled_from(self, 'can_edit')
                self._url.on('keydown.enter', self._analyze)
                self._url.on('focus', lambda: self._set_focus(True))
                self._url.on('blur', lambda: self._set_focus(False))
                monitor_switch = ui.switch(on_change=self._toggle_listener).props('checked-icon=content_paste') \
                    .tooltip('Monitor clipboard').props('aria-label="Monitor clipboard"') \
                    .bind_value_from(self._listener, 'enabled')
                monitor_switch.bind_text_from(self._listener, 'enabled',
                    lambda active: 'Clipboard active' if active else 'Clipboard inactive') \
                    .classes('text-sm w-36')
                ui.button('Analyze', icon='search', on_click=self._analyze) \
                    .props('unelevated no-caps').classes('h-10 w-36').bind_enabled_from(self, 'can_edit')
            # A fixed-height row keeps the preview from shifting.
            with ui.row().classes('w-full h-6 items-center gap-2 flex-nowrap'):
                ui.label().bind_text_from(self._listener, 'message') \
                    .bind_visibility_from(self._listener, 'enabled').classes('text-xs text-gray-500 truncate')
                ui.button('Use this link', on_click=self._use_candidate).props('flat dense no-caps size=sm') \
                    .bind_visibility_from(self, 'has_candidate').bind_enabled_from(self, 'can_edit')

    def _build_preview(self) -> None:
        """Keep a fixed preview area for skeletons and media metadata."""
        with ui.card().props('bordered flat').classes('w-full shrink-0 rounded-lg p-3'):
            with ui.row().classes('w-full items-start gap-3 flex-nowrap h-32'):
                with ui.element('div').classes('w-56 h-32 shrink-0'):
                    ui.skeleton(height='100%', width='100%') \
                        .bind_visibility_from(self, 'media_ready', value=False)
                    self._thumbnail = ui.image().props('fit=contain position="top center"') \
                        .classes('w-full h-full rounded-md').bind_visibility_from(self, 'media_ready')
                    with self._thumbnail.add_slot('loading'):
                        ui.skeleton(height='100%', width='100%')
                    with self._thumbnail.add_slot('error'):
                        self._build_thumbnail_placeholder()
                    with self._thumbnail:
                        self._build_thumbnail_placeholder().bind_visibility_from(
                            self._controller, 'media', lambda media: bool(media and not media.thumbnail))
                with ui.column().classes('flex-1 min-w-0 gap-2'):
                    with ui.column().classes('w-full gap-2').bind_visibility_from(self, 'media_ready', value=False):
                        ui.skeleton('text', width='85%', height='28px')
                        for width in ('40%', '25%', '45%'):
                            ui.skeleton('text', width=width, height='20px')
                    with ui.column().classes('w-full gap-2').bind_visibility_from(self, 'media_ready'):
                        ui.label().bind_text_from(self._controller, 'media', lambda m: m.title if m else '') \
                            .classes('text-lg font-semibold leading-snug line-clamp-2 break-words')
                        ui.label().bind_text_from(self._controller, 'media',
                            lambda m: f'Platform : {m.site}' if m else '').classes('text-sm')
                        ui.label().bind_text_from(self._controller, 'media',
                            lambda m: f'Duration : {self._duration(m.duration)}' if m else '').classes('text-sm')
                        ui.label().bind_text_from(self._controller, 'media',
                            lambda m: f'Channel : {m.channel or "Unspecified"}' if m else '') \
                            .classes('text-sm truncate w-full')

    @staticmethod
    def _build_thumbnail_placeholder() -> ui.column:
        """Show the same placeholder for missing and failed thumbnails."""
        with ui.column().classes('absolute-full items-center justify-center gap-2 bg-grey-2 text-grey-7') as placeholder:
            ui.icon('image_not_supported', size='32px')
            ui.label('No preview available').classes('text-xs')
        return placeholder

    def _build_formats(self) -> None:
        """Build the basic filters and an internally scrolling format table."""
        with ui.card().props('bordered flat').classes('w-full flex-1 min-h-0 rounded-lg p-3 gap-3 flex-nowrap'):
            ui.label('Download options').classes('text-lg font-semibold shrink-0')
            with ui.row().classes('w-full h-10 items-center flex-nowrap gap-3 shrink-0'):
                ui.label('Format:').classes('w-16 shrink-0 text-sm')
                self._type_filter = ui.toggle({'all': 'All', 'video': 'Video', 'audio': 'Audio'},
                    value='all', on_change=self._type_changed).props('no-caps unelevated dense padding="6px 16px" toggle-color=primary color=grey-2 text-color=grey-8')
                self._type_filter.bind_enabled_from(self, 'can_filter')
                ui.space()
                self._audio = ui.select({}, label='Audio track', on_change=self._choice_changed) \
                    .props('outlined dense').classes('w-72').bind_enabled_from(self, 'can_filter')
                self._audio.set_visibility(False)
            with ui.row().classes('w-full items-center flex-nowrap gap-3 shrink-0'):
                ui.label('Quality:').classes('w-16 shrink-0 text-sm')
                with ui.row().classes('flex-1 min-w-0 overflow-x-auto flex-nowrap'):
                    self._quality_filter = ui.toggle({'': 'All'}, value='', on_change=self._apply_filters) \
                        .props('no-caps unelevated dense padding="6px 16px" toggle-color=primary color=grey-2 text-color=grey-8').classes('flex-nowrap')
                    self._quality_filter.bind_enabled_from(self, 'can_filter')
            with ui.column().classes('w-full flex-1 min-h-0 overflow-hidden gap-2') \
                    .bind_visibility_from(self, 'media_ready', value=False):
                for _ in range(5):
                    ui.skeleton(height='32px', width='100%').classes('shrink-0')
            self._table = ui.table(columns=[{'name': key, 'label': label,
                'field': key, 'align': 'left'} for key, label in
                [('format', 'Format'), ('quality', 'Quality'), ('audio', 'Audio'), ('size', 'Size')]], rows=[], row_key='id',
                selection='single', pagination=0, on_select=self._selected) \
                .props('flat bordered dense hide-bottom virtual-scroll') \
                .classes('format-table w-full flex-1 min-h-0')
            self._table.bind_visibility_from(self, 'media_ready')
            self._table.on('rowClick', self._row_clicked, args=[[], ['id']])

    def _build_status(self) -> None:
        """Show application status and transfer progress below the actions."""
        with ui.card().props('bordered flat').classes('w-full rounded-lg p-3 gap-2 shrink-0'):
            with ui.row().classes('w-full items-center justify-between h-5 flex-nowrap'):
                ui.label('Application status').classes('text-sm font-medium')
                ui.button('Open folder', icon='folder_open', on_click=self._open_result) \
                    .props('flat dense no-caps size=sm').bind_visibility_from(self._controller, 'result', bool)
            self._bar = ui.linear_progress(value=0, show_value=False).props('rounded size=7px') \
                .classes('w-full').bind_value_from(self._controller, 'status', lambda p: p.fraction or 0) \
                .bind_visibility_from(self._controller, 'status',
                                     lambda status: status.phase in {
                                         OperationPhase.DOWNLOADING,
                                         OperationPhase.PROCESSING,
                                     })
            ui.label().bind_text_from(self._controller, 'status', lambda p: p.message) \
                .classes('text-xs text-gray-600 truncate w-full')

    def _build_actions(self) -> None:
        """Group selection, destination and download actions above the status."""
        with ui.card().props('bordered flat').classes('w-full rounded-lg p-3 shrink-0'):
            with ui.row().classes('w-full items-stretch gap-3 flex-nowrap'):
                with ui.card().props('flat bordered').classes('flex-1 min-w-0 p-2 gap-1 justify-center'):
                    ui.label('Selected format').classes('text-xs text-gray-500')
                    ui.label().bind_text_from(self, 'selection_summary').classes('text-sm font-medium truncate w-full')
                with ui.card().props('flat bordered').classes('flex-1 min-w-0 p-2 gap-1 justify-center'):
                    ui.label('Folder').classes('text-xs text-gray-500')
                    destination = ui.label().bind_text_from(self._controller, 'destination', str) \
                        .classes('text-sm truncate w-full')
                    with destination:
                        ui.tooltip().bind_text_from(self._controller, 'destination', str)
                ui.button('Change folder', icon='folder_open', on_click=self._choose_folder) \
                    .props('outline no-caps').bind_enabled_from(self, 'can_edit')
                ui.button('Download', icon='download', on_click=self._download) \
                    .props('unelevated no-caps').classes('w-44').bind_enabled_from(self, 'can_download')

    @staticmethod
    def _duration(seconds: float | None) -> str:
        """Format the duration as minutes and seconds, adding hours when needed."""
        if seconds is None:
            return 'Unknown'
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'

    def _set_focus(self, focused: bool) -> None:
        """Prevent clipboard autofill while the user is editing the URL."""
        self._focused = focused

    def _reset_media_view(self) -> None:
        """Restore the initial catalog, filters and preview in place."""
        self._ready = False
        self._options = {}
        self._updating = True
        try:
            self._table.selected = []
            self._table.rows = []
            self._table.update()
            self._type_filter.set_value('all')
            self._quality_filter.set_options({'': 'All'}, value='')
            self._audio.set_options({}, value=None)
        finally:
            self._updating = False
        self._audio.set_visibility(False)
        self._thumbnail.set_source('')

    def _url_changed(self) -> None:
        """Invalidate the catalog when the URL changes."""
        if self.can_edit:
            value = self._url.value or ''
            self._controller.change_url(value)
            self._reset_media_view()
            if not value.strip():
                self._listener.set_enabled(False)

    def _toggle_listener(self, event) -> None:
        """Toggle monitoring and immediately read the clipboard."""
        self._listener.set_enabled(event.value)
        self._poll_clipboard()

    def _poll_clipboard(self) -> None:
        """Read clipboard changes and let bindings update the labels."""
        changed = self._listener.poll()
        if changed and self._listener.candidate and self.can_edit and not self._focused and not self._url.value:
            self._url.set_value(self._listener.candidate)

    def _use_candidate(self) -> None:
        """Use the suggested URL without starting analysis."""
        if self.can_edit:
            self._listener.poll()
            if self._listener.candidate:
                self._url.set_value(self._listener.candidate)

    def _set_working(self, working: bool) -> None:
        """Update the state used by bindings and block table interaction."""
        self._working = working
        if working:
            self._table.props('inert loading')
        else:
            self._table.props(remove='inert loading')

    async def _analyze(self) -> None:
        """Run analysis outside the UI thread and populate the available formats."""
        if not self.can_edit:
            return
        self._controller.change_url(self._url.value or '')
        self._reset_media_view()
        await self._run_operation(self._controller.analyze, self._display_media)

    def _display_media(self) -> None:
        """Update existing components with the analyzed media."""
        media = self._controller.media
        if media is None:
            return
        self._updating = True
        try:
            self._type_filter.set_value('all')
            heights = sorted({fmt.height for fmt in media.formats if fmt.height}, reverse=True)
            self._quality_filter.set_options({'': 'All', **{str(h): f'{h}p' for h in heights}}, value='')
            self._table.selected = []
            tracks = [fmt for fmt in media.formats if fmt.kind == StreamKind.AUDIO]
            self._audio.set_options({'': 'No audio', **{
                track.id: f'{track.language or "Default"} - {track.extension.upper()} ({track.bitrate or "?"} kbps)'
                for track in tracks}}, value='')
        finally:
            self._updating = False
        self._thumbnail.set_source(media.thumbnail or '')
        best_audio = tracks[-1] if tracks else None
        choices = [DownloadChoice(fmt, best_audio if fmt.kind == StreamKind.VIDEO else None)
                   for fmt in reversed(media.formats)]
        # Offer one MP3 conversion per language, using the preferred audio source.
        sources = tracks or [fmt for fmt in media.formats if fmt.audio_codec not in (None, 'none')]
        by_language = {fmt.language: fmt for fmt in sources}
        choices = [DownloadChoice(fmt, _mp3=True) for fmt in by_language.values()] + choices
        self._options = {str(index): choice for index, choice in enumerate(choices)}
        self._apply_filters()
        self._ready = True

    def _apply_filters(self) -> None:
        """Apply local filters and clear a selection that becomes hidden."""
        media = self._controller.media
        if self._updating or media is None or (self._working and self._ready):
            return
        kind = self._type_filter.value
        height = self._quality_filter.value
        self._table.rows = [{'id': key, **describe_choice(choice)} for key, choice in self._options.items()
            if (not height or (not choice.mp3 and str(choice.primary.height) == height))
            and (kind == 'all'
                 or (kind == 'audio' and (choice.mp3 or choice.primary.kind == StreamKind.AUDIO))
                 or (kind == 'video' and not choice.mp3 and choice.primary.kind in {StreamKind.VIDEO, StreamKind.COMBINED}))]
        if self._table.selected and not any(row['id'] == self._table.selected[0]['id'] for row in self._table.rows):
            self._table.selected = []
            self._controller.select(None)
            self._audio.set_visibility(False)
        self._table.update()

    def _type_changed(self) -> None:
        """Clear video resolution when switching to audio options."""
        if self._type_filter.value == 'audio':
            self._quality_filter.set_value('')
        self._apply_filters()

    def _selected_choice(self) -> DownloadChoice | None:
        """Resolve the selected row without confusing conversions with sources."""
        if not self._table.selected:
            return None
        return self._options.get(self._table.selected[0]['id'])

    def _row_clicked(self, event) -> None:
        """Allow selection by clicking the text of a standard table row."""
        if self.can_filter:
            row = next((row for row in self._table.rows if row['id'] == event.args[1]['id']), None)
            if row:
                self._table.selected = [row]
                self._table.update()
                self._selected()

    def _selected(self) -> None:
        """Initialize additional options without exposing intermediate selections."""
        if not self.can_filter:
            return
        choice = self._selected_choice()
        self._updating = True
        try:
            self._audio.set_value(choice.audio.id if choice and choice.audio else '')
        finally:
            self._updating = False
        self._audio.set_visibility(bool(choice and choice.primary.kind == StreamKind.VIDEO
                                        and len(self._audio.options) > 1))
        self._controller.select(choice)

    def _choice_changed(self) -> None:
        """Pass a validated choice to the controller and update through bindings."""
        if not self.can_filter or self._updating:
            return
        choice = self._selected_choice()
        media = self._controller.media
        if not choice or not media:
            self._controller.select(None)
            return
        if choice.primary.kind == StreamKind.VIDEO:
            audio = next((track for track in media.formats if track.id == self._audio.value), None)
            choice = DownloadChoice(choice.primary, audio)
            key = self._table.selected[0]['id']
            self._options[key] = choice
            for row in self._table.rows:
                if row['id'] == key:
                    row.update(describe_choice(choice))
                    break
            self._table.update()
        self._controller.select(choice)

    async def _choose_folder(self) -> None:
        """Open the native folder picker, preserving the destination on cancellation."""
        if not self.can_edit:
            return
        try:
            import webview
            folders = await app.native.main_window.create_file_dialog(
                dialog_type=webview.FileDialog.FOLDER, directory=str(self._controller.destination))
            if folders and self.can_edit:
                self._controller.change_destination(Path(folders[0]))
                try:
                    save_destination(self._controller.destination)
                except OSError:
                    ui.notify('Folder selected for this session; preference could not be saved.', type='warning')
        except Exception as error:
            self._show_error(error)

    async def _download(self) -> None:
        """Download outside the UI thread while bindings track progress."""
        if not self.can_download:
            return
        await self._run_operation(self._controller.download, track_progress=True)

    async def _run_operation(self, operation: Callable[[], None],
                             on_success: Callable[[], None] | None = None,
                             track_progress: bool = False) -> None:
        """Run a worker with shared progress, error handling and UI cleanup."""
        self._set_working(True)
        timer = ui.timer(0.25, self._update_progress_mode) if track_progress else None
        if track_progress:
            self._bar.props('indeterminate')
        try:
            await run.io_bound(operation)
            if on_success:
                on_success()
        except Exception as error:
            self._show_error(error)
        finally:
            if timer:
                timer.cancel()
                self._bar.props(remove='indeterminate')
            self._set_working(False)

    def _update_progress_mode(self) -> None:
        """Switch between measured progress and indeterminate processing."""
        if self._controller.status.fraction is None:
            self._bar.props('indeterminate')
        else:
            self._bar.props(remove='indeterminate')

    def _open_result(self) -> None:
        """Open the folder containing the confirmed output file."""
        try:
            if self._controller.result:
                open_folder(self._controller.result.path.parent)
        except OSError as error:
            self._show_error(error)

    def _show_error(self, error: Exception) -> None:
        """Display an error in a standard NiceGUI dialog."""
        logging.getLogger(__name__).error('Operation failed: %s', error)
        with ui.dialog() as dialog, ui.card().classes('max-w-xl'):
            ui.label('Unable to complete the operation').classes('text-lg font-semibold')
            ui.label(str(error)).classes('break-all whitespace-pre-wrap')
            ui.button('Close', on_click=dialog.close)
        dialog.open()
