import ctypes
import ctypes.util
import os
import sys
import threading
from pathlib import Path
from tkinter import filedialog, simpledialog

# Make bundled ffmpeg (PyInstaller) and Homebrew ffmpeg findable before any imports.
_extra_paths = []
if getattr(sys, 'frozen', False):
    _extra_paths.append(sys._MEIPASS)
_extra_paths += ['/opt/homebrew/bin', '/usr/local/bin']
for _p in _extra_paths:
    if _p not in os.environ.get('PATH', ''):
        os.environ['PATH'] = _p + ':' + os.environ.get('PATH', '')

import customtkinter as ctk

from soundklaut import (
    download_track, set_metadata, trim_trailing_silence,
    find_blackhole_device, record_from_audio_capture,
    spotify_credentials_saved, save_spotify_credentials, load_spotify_credentials,
)

ctk.set_appearance_mode('System')
ctk.set_default_color_theme('blue')

_DEFAULT_OUTPUT = str(Path.home() / 'Downloads')


def _macos_activate():
    """Promote process to foreground GUI app and bring window to front."""
    try:
        libobjc = ctypes.CDLL(ctypes.util.find_library('objc'))
        libobjc.objc_getClass.restype = ctypes.c_void_p
        libobjc.sel_registerName.restype = ctypes.c_void_p
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        nsapp = libobjc.objc_msgSend(
            ctypes.c_void_p(libobjc.objc_getClass(b'NSApplication')),
            ctypes.c_void_p(libobjc.sel_registerName(b'sharedApplication')),
        )

        set_policy = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long
        )(ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p))
        set_policy(
            nsapp,
            ctypes.c_void_p(libobjc.sel_registerName(b'setActivationPolicy:')),
            0,  # NSApplicationActivationPolicyRegular
        )

        activate = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool
        )(ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p))
        activate(
            nsapp,
            ctypes.c_void_p(libobjc.sel_registerName(b'activateIgnoringOtherApps:')),
            True,
        )
    except Exception:
        pass


class SoundklautApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title('soundklaut')
        self.geometry('640x760')
        self.resizable(True, True)
        self._indeterminate_job = None
        self._build_ui()
        self.after(0, self._show)

    def _show(self):
        if sys.platform == 'darwin':
            _macos_activate()
        self.deiconify()
        self.update()
        self.lift()
        self.focus_force()

    def _build_ui(self):
        pad = {'padx': 16, 'pady': 6}

        ctk.CTkLabel(
            self,
            text='URLs — SoundCloud oder Spotify (eine pro Zeile):',
            anchor='w',
        ).pack(fill='x', **pad)
        self.urls_box = ctk.CTkTextbox(self, height=110)
        self.urls_box.pack(fill='x', **pad)

        ctk.CTkLabel(
            self,
            text='Playlist / Album / Podcast-Show-URL:',
            anchor='w',
        ).pack(fill='x', **pad)
        self.playlist_entry = ctk.CTkEntry(
            self,
            placeholder_text=(
                'https://soundcloud.com/artist/sets/…  '
                'oder  https://open.spotify.com/album/…'
            ),
        )
        self.playlist_entry.pack(fill='x', **pad)

        # Spotify-Login-Status
        login_row = ctk.CTkFrame(self, fg_color='transparent')
        login_row.pack(fill='x', padx=16, pady=(0, 4))
        logged_in = spotify_credentials_saved()
        self._login_status = ctk.CTkLabel(
            login_row,
            text='Spotify ✓ eingeloggt' if logged_in else 'Spotify: nicht eingeloggt (für Podcast-Download nötig)',
            text_color='#4caf50' if logged_in else '#f0a500',
            font=ctk.CTkFont(size=11),
            anchor='w',
        )
        self._login_status.pack(side='left', fill='x', expand=True)
        ctk.CTkButton(
            login_row, text='Spotify Login', width=110,
            command=self._spotify_login,
        ).pack(side='right')

        ctk.CTkLabel(self, text='Ausgabe-Ordner:', anchor='w').pack(fill='x', **pad)
        out_row = ctk.CTkFrame(self, fg_color='transparent')
        out_row.pack(fill='x', **pad)
        self.output_entry = ctk.CTkEntry(out_row, placeholder_text=_DEFAULT_OUTPUT)
        self.output_entry.pack(side='left', fill='x', expand=True)
        ctk.CTkButton(
            out_row, text='Browse', width=80, command=self._browse
        ).pack(side='left', padx=(8, 0))

        opts_row = ctk.CTkFrame(self, fg_color='transparent')
        opts_row.pack(fill='x', **pad)
        self.trim_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts_row, text='Silence trimmen', variable=self.trim_var).pack(
            side='left'
        )
        ctk.CTkLabel(opts_row, text='   Threshold (dBFS):').pack(side='left')
        self.threshold_entry = ctk.CTkEntry(opts_row, width=70)
        self.threshold_entry.insert(0, '-50')
        self.threshold_entry.pack(side='left', padx=(4, 0))

        self.download_btn = ctk.CTkButton(
            self, text='Download starten', command=self._start_download
        )
        self.download_btn.pack(pady=(12, 4), padx=16, fill='x')

        self.progress_label = ctk.CTkLabel(self, text='', anchor='w')
        self.progress_label.pack(fill='x', padx=16)
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill='x', padx=16, pady=(2, 8))
        self.progress_bar.pack_forget()

        # ── Audio-Capture-Sektion ──────────────────────────────────────────
        sep = ctk.CTkFrame(self, height=1, fg_color='gray40')
        sep.pack(fill='x', padx=16, pady=(4, 0))

        cap_header = ctk.CTkFrame(self, fg_color='transparent')
        cap_header.pack(fill='x', padx=16, pady=(6, 2))
        ctk.CTkLabel(
            cap_header,
            text='🎙  Audio-Capture  (für DRM-geschützte / Spotify-exklusive Inhalte)',
            anchor='w',
            font=ctk.CTkFont(size=12, weight='bold'),
        ).pack(side='left')

        bh_ok = find_blackhole_device() is not None
        self._bh_status = ctk.CTkLabel(
            cap_header,
            text='BlackHole ✓' if bh_ok else 'BlackHole nicht gefunden',
            text_color='#4caf50' if bh_ok else '#f44336',
            font=ctk.CTkFont(size=11),
        )
        self._bh_status.pack(side='right')

        cap_hint = ctk.CTkLabel(
            self,
            text=(
                'Anleitung: 1. BlackHole installieren  2. Systemeinst. → Ton → Ausgabe → BlackHole 2ch\n'
                '3. Episode in Spotify starten  4. Aufnahme starten  5. Stoppen wenn fertig'
            ),
            anchor='w',
            font=ctk.CTkFont(size=11),
            text_color='gray60',
            justify='left',
        )
        cap_hint.pack(fill='x', padx=16, pady=(0, 4))

        cap_name_row = ctk.CTkFrame(self, fg_color='transparent')
        cap_name_row.pack(fill='x', padx=16, pady=(0, 4))
        ctk.CTkLabel(cap_name_row, text='Dateiname:', width=80, anchor='w').pack(side='left')
        self.cap_name_entry = ctk.CTkEntry(
            cap_name_row, placeholder_text='z.B.  Künstler - Titel'
        )
        self.cap_name_entry.pack(side='left', fill='x', expand=True)

        cap_btn_row = ctk.CTkFrame(self, fg_color='transparent')
        cap_btn_row.pack(fill='x', padx=16, pady=(0, 8))
        self._capture_stop_event = threading.Event()
        self.capture_start_btn = ctk.CTkButton(
            cap_btn_row, text='🎙 Aufnahme starten',
            width=180, command=self._start_capture,
        )
        self.capture_start_btn.pack(side='left', padx=(0, 8))
        self.capture_stop_btn = ctk.CTkButton(
            cap_btn_row, text='⏹ Stoppen',
            width=120, state='disabled', command=self._stop_capture,
            fg_color='#c0392b', hover_color='#e74c3c',
        )
        self.capture_stop_btn.pack(side='left')

        sep2 = ctk.CTkFrame(self, height=1, fg_color='gray40')
        sep2.pack(fill='x', padx=16, pady=(0, 4))
        # ──────────────────────────────────────────────────────────────────

        ctk.CTkLabel(self, text='Protokoll:', anchor='w').pack(fill='x', padx=16)
        self.log_box = ctk.CTkTextbox(self, state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=16, pady=(0, 16))

    def _spotify_login(self):
        """Öffnet einen Dialog für Spotify-Email + Passwort."""
        dialog = ctk.CTkToplevel(self)
        dialog.title('Spotify Login')
        dialog.geometry('380x200')
        dialog.grab_set()
        dialog.resizable(False, False)

        ctk.CTkLabel(dialog, text='Spotify Email:', anchor='w').pack(fill='x', padx=20, pady=(16, 2))
        email_entry = ctk.CTkEntry(dialog, placeholder_text='deine@email.com')
        email_entry.pack(fill='x', padx=20)

        ctk.CTkLabel(dialog, text='Passwort:', anchor='w').pack(fill='x', padx=20, pady=(8, 2))
        pw_entry = ctk.CTkEntry(dialog, show='•', placeholder_text='••••••••')
        pw_entry.pack(fill='x', padx=20)

        def _save():
            email = email_entry.get().strip()
            pw = pw_entry.get()
            if email and pw:
                save_spotify_credentials(email, pw)
                self._login_status.configure(
                    text='Spotify ✓ eingeloggt', text_color='#4caf50'
                )
                dialog.destroy()

        ctk.CTkButton(dialog, text='Speichern', command=_save).pack(pady=16)

    def _browse(self):
        path = filedialog.askdirectory()
        if path:
            self.output_entry.delete(0, 'end')
            self.output_entry.insert(0, path)

    def _log(self, text):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', text + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def _start_download(self):
        urls = [
            u.strip()
            for u in self.urls_box.get('1.0', 'end').splitlines()
            if u.strip()
        ]
        playlist = self.playlist_entry.get().strip()
        if playlist:
            urls.append(playlist)

        if not urls:
            self._log('⚠  Keine URLs eingegeben.')
            return

        try:
            threshold = float(self.threshold_entry.get() or -50)
        except ValueError:
            self._log('⚠  Ungültiger Threshold-Wert (muss eine Zahl sein, z.B. -50).')
            return

        output_dir_str = self.output_entry.get().strip() or _DEFAULT_OUTPUT
        output_dir = Path(output_dir_str).expanduser().resolve()
        allow_playlist = bool(playlist)
        trim = self.trim_var.get()

        self.download_btn.configure(state='disabled')
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.configure(state='disabled')
        self.progress_bar.pack(fill='x', padx=16, pady=(2, 8))
        self.progress_bar.set(0)

        threading.Thread(
            target=self._run_downloads,
            args=(urls, output_dir, allow_playlist, trim, threshold),
            daemon=True,
        ).start()

    def _run_downloads(self, urls, output_dir, allow_playlist, trim, threshold):
        output_dir.mkdir(parents=True, exist_ok=True)
        n = len(urls)

        for i, url in enumerate(urls):
            track_name = [url]

            def on_progress(
                downloaded_bytes, total_bytes, filename,
                _i=i, _n=n, _track_name=track_name,
            ):
                if filename:
                    stem = Path(filename).stem
                    if stem != _track_name[0]:
                        _track_name[0] = stem
                label = f'  [{_i + 1}/{_n}]  {_track_name[0]}'
                if total_bytes:
                    value = downloaded_bytes / total_bytes
                    self.after(
                        0,
                        lambda v=value, l=label: self._update_progress(v, l, False),
                    )
                else:
                    self.after(
                        0, lambda l=label: self._update_progress(None, l, True)
                    )

            status, result, total = download_track(
                url, output_dir, allow_playlist,
                progress_callback=on_progress,
            )

            if status == 'downloaded':
                trim_note = ''
                if trim and result and result.exists():
                    try:
                        trimmed, secs = trim_trailing_silence(
                            result,
                            silence_thresh=threshold,
                            min_silence_len=2000,
                        )
                        if trimmed:
                            trim_note = f'  (trimmed {secs:.1f}s)'
                    except Exception as e:
                        self.after(0, lambda e=e: self._log(f'  ⚠  trim failed: {e}'))

                if result and result.exists():
                    info_json = result.with_suffix('.info.json')
                    if info_json.exists():
                        try:
                            set_metadata(result, info_json)
                        except Exception as e:
                            self.after(
                                0,
                                lambda s=result.stem, e=e: self._log(
                                    f'  ⚠  {s}  (metadata failed: {e})'
                                ),
                            )

                size_str = f'  {_format_bytes(total)}' if total else ''
                name = track_name[0]
                self.after(
                    0,
                    lambda n=name, t=trim_note, s=size_str: self._log(
                        f'  ✓  {n}{t}{s}'
                    ),
                )

            elif status == 'skipped':
                name = track_name[0]
                self.after(
                    0,
                    lambda n=name: self._log(f'  ⏭  {n}  already downloaded'),
                )

            else:
                name = track_name[0]
                if result == 'SPOTIFY_NO_CREDENTIALS':
                    self.after(0, lambda: self._log(
                        '  ✗  Spotify-Login fehlt — klicke oben auf "Spotify Login"'
                    ))
                else:
                    self.after(
                        0,
                        lambda n=name, r=result: self._log(f'  ✗  {n}  {r}'),
                    )

        self.after(0, self._finish_downloads)

    def _update_progress(self, value, label, indeterminate):
        self.progress_label.configure(text=label)
        if self._indeterminate_job:
            self.after_cancel(self._indeterminate_job)
            self._indeterminate_job = None
        if indeterminate:
            self._animate_indeterminate()
        else:
            self.progress_bar.set(value)

    def _animate_indeterminate(self, pos=0.0):
        self.progress_bar.set(pos)
        next_pos = (pos + 0.02) % 1.0
        self._indeterminate_job = self.after(
            50, lambda: self._animate_indeterminate(next_pos)
        )

    # ── Audio-Capture ──────────────────────────────────────────────────────────

    def _start_capture(self):
        name = self.cap_name_entry.get().strip() or 'Spotify-Aufnahme'
        output_dir_str = self.output_entry.get().strip() or _DEFAULT_OUTPUT
        output_dir = Path(output_dir_str).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        self._capture_stop_event.clear()
        self.capture_start_btn.configure(state='disabled')
        self.capture_stop_btn.configure(state='normal')
        self.progress_bar.pack(fill='x', padx=16, pady=(2, 8))
        self.progress_bar.set(0)
        self._log(f'🎙  Aufnahme gestartet: {name}')
        self._log('     Stelle sicher dass BlackHole als Audioausgabe gewählt ist')
        self._log('     und die Episode in Spotify läuft.')

        threading.Thread(
            target=self._run_capture,
            args=(name, output_dir),
            daemon=True,
        ).start()

    def _stop_capture(self):
        self._capture_stop_event.set()

    def _run_capture(self, name, output_dir):
        def on_progress(downloaded_bytes, total_bytes, filename):
            self.after(0, lambda f=filename: self.progress_label.configure(text=f'  {f}'))
            self.after(0, lambda: self._animate_indeterminate())

        status, result, _ = record_from_audio_capture(
            output_dir=output_dir,
            filename_stem=name,
            stop_event=self._capture_stop_event,
            progress_callback=on_progress,
        )

        if status == 'downloaded':
            self.after(0, lambda: self._log(f'  ✓  Gespeichert: {result.name}'))
        else:
            self.after(0, lambda r=result: self._log(f'  ✗  {r}'))

        self.after(0, self._finish_capture)

    def _finish_capture(self):
        if self._indeterminate_job:
            self.after_cancel(self._indeterminate_job)
            self._indeterminate_job = None
        self.progress_bar.set(1.0)
        self.progress_label.configure(text='  Fertig.')
        self.capture_start_btn.configure(state='normal')
        self.capture_stop_btn.configure(state='disabled')

    # ──────────────────────────────────────────────────────────────────────────

    def _finish_downloads(self):
        if self._indeterminate_job:
            self.after_cancel(self._indeterminate_job)
            self._indeterminate_job = None
        self.progress_bar.set(1.0)
        self.progress_label.configure(text='  Fertig.')
        self.download_btn.configure(state='normal')


def _format_bytes(n):
    if n is None:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


if __name__ == '__main__':
    app = SoundklautApp()
    app.mainloop()
