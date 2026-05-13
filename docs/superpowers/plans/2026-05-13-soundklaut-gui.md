# soundklaut GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `soundklaut_gui.py` — a CustomTkinter desktop window that lets the user paste SoundCloud URLs, configure options, and see live download progress and results without using the terminal.

**Architecture:** Single new file `soundklaut_gui.py` in `soundcloud-dl/`. Imports `download_track`, `trim_trailing_silence`, `set_metadata` directly from `soundklaut.py`. Downloads run in a `threading.Thread`; all UI updates go through `self.after(0, callback)` (Tkinter's thread-safe dispatch). No changes to `soundklaut.py` or existing tests.

**Tech Stack:** Python 3.10+, customtkinter>=5.2.0, tkinter (stdlib), threading (stdlib), existing soundklaut.py functions

---

### Task 1: Dependency + window scaffold + input widgets

**Files:**
- Modify: `soundcloud-dl/requirements.txt`
- Create: `soundcloud-dl/soundklaut_gui.py`

> **Note:** This is a GUI — no automated unit tests exist. Each task ends with a smoke test (run the script, verify visually).

- [ ] **Step 1: Add customtkinter to requirements.txt**

Open `soundcloud-dl/requirements.txt` and add this line:

```
customtkinter>=5.2.0
```

Then install it:

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && pip3 install customtkinter
```

Expected: `Successfully installed customtkinter-...`

- [ ] **Step 2: Create soundklaut_gui.py with full UI layout**

Create `soundcloud-dl/soundklaut_gui.py` with this complete content:

```python
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from soundklaut import download_track, set_metadata, trim_trailing_silence

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class SoundklautApp(ctk.CTk):
    def __init__(self):
        super().__init__()
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
```

- [ ] **Step 3: Smoke-test — window opens**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 soundklaut_gui.py
```

Expected: A window titled "soundklaut" opens with all input fields, a Download button, and a log area visible. Close the window.

- [ ] **Step 4: Smoke-test — Browse button works**

Run the app again, click "Browse". Expected: a native macOS folder picker dialog opens. Select any folder — the path appears in the Ausgabe field.

- [ ] **Step 5: Smoke-test — validation**

Run the app. Click "Download starten" without entering any URL. Expected: log area shows `⚠  Keine URLs eingegeben.`

Clear the Threshold field, type `abc`, click Download starten. Expected: log area shows `⚠  Ungültiger Threshold-Wert...`

- [ ] **Step 6: Smoke-test — existing tests still pass**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -q 2>&1 | tail -3
```

Expected: `27 passed`

- [ ] **Step 7: Commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add soundklaut_gui.py requirements.txt && git commit -m "feat: add CustomTkinter GUI (soundklaut_gui.py)"
```

---

### Task 2: End-to-end smoke test with a real URL

**Files:**
- No code changes — this task verifies the full download flow works end-to-end.

- [ ] **Step 1: Run the GUI with a real SoundCloud URL**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 soundklaut_gui.py
```

Paste a valid SoundCloud track URL into the URL box. Leave output as `downloads`. Click "Download starten".

Expected behaviour in sequence:
1. Download button becomes disabled
2. Progress bar appears and animates
3. Progress label shows `[1/1]  Artist - Title` (updated from URL once yt-dlp fires the first hook)
4. Progress bar fills as download progresses
5. After download: log line appears: `  ✓  Artist - Title  3.2 MB` (size varies)
6. "Download starten" button re-enables
7. Progress label shows `  Fertig.`

- [ ] **Step 2: Run again with the same URL — verify skip**

Click "Download starten" again with the same URL (archive file now exists).

Expected: log shows `  ⏭  Artist - Title  already downloaded`

- [ ] **Step 3: Verify MP3 is in the downloads folder**

```bash
ls /Users/romangerdes/Documents/Privat/Music/soundcloud-dl/downloads/*.mp3
```

Expected: the downloaded file is there.

---

## Self-Review

**Spec coverage:**
- ✓ CustomTkinter window with all input fields
- ✓ URL textbox (multiline, one per line)
- ✓ Playlist-URL entry
- ✓ Ausgabe entry + Browse button (native folder picker)
- ✓ Silence trimmen checkbox (default: checked) + threshold entry (default: -50)
- ✓ Download button disabled during download
- ✓ Progress bar with label, live updates via `progress_callback`
- ✓ Indeterminate animation when `total_bytes` is None
- ✓ Log area: ✓ / ⏭ / ✗ result lines, trim notes, size, warnings
- ✓ Threading with `self.after(0, ...)` for thread-safe UI updates
- ✓ No changes to `soundklaut.py` or tests
- ✓ `customtkinter>=5.2.0` added to requirements.txt

**Placeholder scan:** None.

**Type consistency:**
- `on_progress(downloaded_bytes, total_bytes, filename)` — matches `download_track`'s callback signature exactly
- `download_track` returns `(status, result, total)` — unpacked as 3-tuple throughout
- `trim_trailing_silence(result, silence_thresh=threshold, min_silence_len=2000)` — matches function signature in soundklaut.py
- `set_metadata(result, info_json)` — matches function signature in soundklaut.py
