# soundklaut — GUI Window
_Date: 2026-05-13_

## Overview

Add a desktop GUI window (`soundklaut_gui.py`) that lets the user paste SoundCloud URLs, configure download options, and see per-track progress and results — all without using the terminal.

---

## Window Layout

```
┌─────────────────────────────────────────────┐
│  soundklaut                                 │
├─────────────────────────────────────────────┤
│  URLs (eine pro Zeile):                     │
│  ┌─────────────────────────────────────┐    │
│  │                                     │    │
│  │                                     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Playlist-URL:  [                        ]  │
│                                             │
│  Ausgabe:  [~/Music/downloads   ] [Browse]  │
│                                             │
│  [x] Silence trimmen   Threshold: [ -50 ]   │
│                                             │
│          [ Download starten ]               │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │ ✓  Artist - Title          3.2 MB   │    │
│  │ ⏭  Artist - Title 2                 │    │
│  │ ✗  artist/track  HTTP 404           │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

During a download, a progress bar appears below the Download button (one bar, updates per track). The Download button is disabled while a download is running.

---

## Components

### Input Fields

| Field | Widget | Maps to |
|-------|--------|---------|
| URLs (multiline) | `CTkTextbox` | positional `urls` args |
| Playlist-URL | `CTkEntry` | `--playlist` |
| Ausgabe | `CTkEntry` + Browse button | `--output` |
| Silence trimmen | `CTkCheckBox` (default: checked) | `--no-trim` (inverted) |
| Threshold (dBFS) | `CTkEntry` (default: `-50`) | `--silence-threshold` |

The Browse button opens a native folder picker (`tkinter.filedialog.askdirectory`).

### Progress Bar

A single `CTkProgressBar` below the Download button. Before downloading:
- hidden (or value 0)

During download of track `i` of `n`:
- Label: `[i/n]  track_name`
- Bar value: `downloaded_bytes / total_bytes` (0.0–1.0)
- If `total_bytes` is None (unknown size): indeterminate mode (bar animates)

After all downloads: bar is reset/hidden.

### Log Area

A `CTkTextbox` (read-only, scrollable) below the progress bar. One line appended per track after it finishes:

```
  ✓  Artist - Title                3.2 MB
  ✓  Artist - Title 2  (trimmed 2.3s)  2.8 MB
  ⏭  Artist - Title 3  already downloaded
  ✗  artist/track  HTTP Error 404
```

Also shows warnings inline (trim failed, metadata failed) in the same text box.

---

## Architecture

### File

- **New file:** `soundcloud-dl/soundklaut_gui.py`
- **No changes** to `soundklaut.py`

### Imports from soundklaut.py

```python
from soundklaut import download_track, trim_trailing_silence, set_metadata
```

`build_urls` is not used — the GUI reads URLs directly from the text box.

### Threading model

Downloads run in a `threading.Thread` to keep the UI responsive. All UI updates from the worker thread go through `window.after(0, callback)` — Tkinter's thread-safe dispatch mechanism.

### Download loop (worker thread)

```python
def _run_downloads(self):
    urls = [u.strip() for u in self.urls_box.get("1.0", "end").splitlines() if u.strip()]
    playlist = self.playlist_entry.get().strip()
    if playlist:
        urls.append(playlist)

    output_dir = Path(self.output_entry.get()).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / 'downloaded.txt'
    allow_playlist = bool(playlist)
    trim = self.trim_var.get()
    threshold = float(self.threshold_entry.get() or -50)
    n = len(urls)

    for i, url in enumerate(urls):
        track_name = url  # updated via progress_callback

        def on_progress(downloaded_bytes, total_bytes, filename,
                        _i=i, _n=n):
            # update progress bar and label via window.after()
            ...

        status, result, total = download_track(
            url, output_dir, archive_path, allow_playlist,
            progress_callback=on_progress,
        )

        # trim, set_metadata, append log line — same logic as soundklaut.py main()
        ...
```

### Progress bar indeterminate mode

CustomTkinter's `CTkProgressBar` does not have a built-in indeterminate animation. When `total_bytes` is `None`, the bar is set to an oscillating value using `window.after()` polling (increment by 0.02 each 50 ms, wrap at 1.0) until the next progress update with a known total arrives.

---

## Error Handling

- **Invalid threshold value** (non-numeric): validated on button click, shows error message in log area before starting.
- **No URLs entered**: button click does nothing / shows "Keine URLs eingegeben" in log.
- **Download error**: shown as `✗ track  error message` in log, does not abort remaining tracks.
- **Trim / metadata errors**: shown as warning line in log, download result line still printed.

---

## Files Changed

- **Create:** `soundcloud-dl/soundklaut_gui.py`
- **No changes** to `soundklaut.py` or `tests/`

---

## Dependencies

```
customtkinter>=5.2.0
```

Add to `requirements.txt`.

---

## Not Included

- No system tray / dock icon
- No settings persistence (output path resets each launch)
- No drag-and-drop URL input
- No dark/light mode toggle (follows system setting via CustomTkinter default)
