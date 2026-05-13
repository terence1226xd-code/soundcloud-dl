import ctypes
import ctypes.util
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from soundklaut import download_track, set_metadata, trim_trailing_silence

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


def _macos_activate():
    """Bring the Python process to the foreground after Tkinter has initialized NSApplication."""
    try:
        libobjc = ctypes.CDLL(ctypes.util.find_library("objc"))
        libobjc.objc_getClass.restype = ctypes.c_void_p
        libobjc.sel_registerName.restype = ctypes.c_void_p
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        nsapp = libobjc.objc_msgSend(
            ctypes.c_void_p(libobjc.objc_getClass(b"NSApplication")),
            ctypes.c_void_p(libobjc.sel_registerName(b"sharedApplication")),
        )
        activate = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool
        )(ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p))
        activate(
            nsapp,
            ctypes.c_void_p(libobjc.sel_registerName(b"activateIgnoringOtherApps:")),
            True,
        )
    except Exception:
        pass


class SoundklautApp(ctk.CTk):
    def __init__(self):
        super().__init__()  # Tkinter initialises NSApplication here
        if sys.platform == "darwin":
            _macos_activate()  # bring to front AFTER NSApp exists
        self.title("soundklaut")
        self.geometry("620x720")
        self.resizable(True, True)
        self._indeterminate_job = None
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 16, "pady": 6}

        ctk.CTkLabel(self, text="URLs (eine pro Zeile):", anchor="w").pack(fill="x", **pad)
        self.urls_box = ctk.CTkTextbox(self, height=100)
        self.urls_box.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Playlist-URL:", anchor="w").pack(fill="x", **pad)
        self.playlist_entry = ctk.CTkEntry(
            self, placeholder_text="https://soundcloud.com/artist/sets/..."
        )
        self.playlist_entry.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Ausgabe:", anchor="w").pack(fill="x", **pad)
        out_row = ctk.CTkFrame(self, fg_color="transparent")
        out_row.pack(fill="x", **pad)
        self.output_entry = ctk.CTkEntry(out_row, placeholder_text="downloads")
        self.output_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            out_row, text="Browse", width=80, command=self._browse
        ).pack(side="left", padx=(8, 0))

        opts_row = ctk.CTkFrame(self, fg_color="transparent")
        opts_row.pack(fill="x", **pad)
        self.trim_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts_row, text="Silence trimmen", variable=self.trim_var).pack(
            side="left"
        )
        ctk.CTkLabel(opts_row, text="   Threshold (dBFS):").pack(side="left")
        self.threshold_entry = ctk.CTkEntry(opts_row, width=70)
        self.threshold_entry.insert(0, "-50")
        self.threshold_entry.pack(side="left", padx=(4, 0))

        self.download_btn = ctk.CTkButton(
            self, text="Download starten", command=self._start_download
        )
        self.download_btn.pack(pady=(12, 4), padx=16, fill="x")

        self.progress_label = ctk.CTkLabel(self, text="", anchor="w")
        self.progress_label.pack(fill="x", padx=16)
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=16, pady=(2, 8))
        self.progress_bar.pack_forget()

        ctk.CTkLabel(self, text="Ausgabe:", anchor="w").pack(fill="x", padx=16)
        self.log_box = ctk.CTkTextbox(self, state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _browse(self):
        path = filedialog.askdirectory()
        if path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, path)

    def _log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start_download(self):
        urls = [
            u.strip()
            for u in self.urls_box.get("1.0", "end").splitlines()
            if u.strip()
        ]
        playlist = self.playlist_entry.get().strip()
        if playlist:
            urls.append(playlist)

        if not urls:
            self._log("⚠  Keine URLs eingegeben.")
            return

        try:
            threshold = float(self.threshold_entry.get() or -50)
        except ValueError:
            self._log("⚠  Ungültiger Threshold-Wert (muss eine Zahl sein, z.B. -50).")
            return

        output_dir_str = self.output_entry.get().strip() or "downloads"
        output_dir = Path(output_dir_str).expanduser().resolve()
        allow_playlist = bool(playlist)
        trim = self.trim_var.get()

        self.download_btn.configure(state="disabled")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.pack(fill="x", padx=16, pady=(2, 8))
        self.progress_bar.set(0)

        threading.Thread(
            target=self._run_downloads,
            args=(urls, output_dir, allow_playlist, trim, threshold),
            daemon=True,
        ).start()

    def _run_downloads(self, urls, output_dir, allow_playlist, trim, threshold):
        output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = output_dir / "downloaded.txt"
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
                label = f"  [{_i + 1}/{_n}]  {_track_name[0]}"
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
                url, output_dir, archive_path, allow_playlist,
                progress_callback=on_progress,
            )

            if status == "downloaded":
                trim_note = ""
                if trim:
                    try:
                        trimmed, secs = trim_trailing_silence(
                            result,
                            silence_thresh=threshold,
                            min_silence_len=2000,
                        )
                        if trimmed:
                            trim_note = f"  (trimmed {secs:.1f}s)"
                    except Exception as e:
                        self.after(0, lambda e=e: self._log(f"  ⚠  trim failed: {e}"))

                info_json = result.with_suffix(".info.json")
                if info_json.exists():
                    try:
                        set_metadata(result, info_json)
                    except Exception as e:
                        self.after(
                            0,
                            lambda s=result.stem, e=e: self._log(
                                f"  ⚠  {s}  (metadata failed: {e})"
                            ),
                        )

                size_str = f"  {_format_bytes(total)}" if total else ""
                name = track_name[0]
                self.after(
                    0,
                    lambda n=name, t=trim_note, s=size_str: self._log(
                        f"  ✓  {n}{t}{s}"
                    ),
                )

            elif status == "skipped":
                name = track_name[0]
                self.after(
                    0,
                    lambda n=name: self._log(f"  ⏭  {n}  already downloaded"),
                )

            else:
                name = track_name[0]
                self.after(
                    0,
                    lambda n=name, r=result: self._log(f"  ✗  {n}  {r}"),
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

    def _finish_downloads(self):
        if self._indeterminate_job:
            self.after_cancel(self._indeterminate_job)
            self._indeterminate_job = None
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="  Fertig.")
        self.download_btn.configure(state="normal")


def _format_bytes(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


if __name__ == "__main__":
    app = SoundklautApp()
    app.mainloop()
