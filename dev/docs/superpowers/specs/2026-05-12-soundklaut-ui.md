# soundklaut — Rich UI Redesign
_Date: 2026-05-12_

## Overview

Replace the bare `console.print` output with a polished Rich terminal UI: styled header, per-track progress bar (speed + ETA) during download, transient bar replaced by a result line, and a styled summary.

---

## Layout

```
 soundklaut  ·  3 tracks  →  ~/Music/downloads

  ⠸  [1/3]  Artist - Title
             ━━━━━━━━━━━━━━░░░░░  68%  3.8 MB/s  0:00:04

  ✓  Artist - Title                          3.2 MB
  ✓  Artist - Title 2   (trimmed 2.3s)       2.8 MB
  ⏭  Artist - Title 3   already downloaded

 ─────────────────────────────────────────────────
  2 downloaded · 1 skipped · 0 failed
```

---

## Components

### Header
```python
console.print(f"\n [bold cyan]soundklaut[/]  ·  {len(urls)} track{'s' if len(urls) != 1 else ''}  →  [dim]{output_dir}[/]\n")
```

### Per-track Progress Bar
- Rich `Progress` with `transient=True` — bar disappears after completion
- Columns: `SpinnerColumn()`, `TextColumn("{task.description}")`, `BarColumn()`, `TaskProgressColumn()`, `TransferSpeedColumn()`, `TimeRemainingColumn()`
- One `Progress` context per URL (not one global context)
- Description: `f"[{i+1}/{n}]  {track_name}"` where `track_name` starts as a shortened URL and updates to `Path(d['filename']).stem` on first `'downloading'` hook event
- If `total_bytes` is None (unknown size): bar shows as indeterminate, speed still shown

### Result Lines
After the progress context exits (bar disappears):
```
  ✓  Artist - Title                          3.2 MB      # downloaded
  ✓  Artist - Title 2   (trimmed 2.3s)       2.8 MB      # downloaded + trimmed
  ⏭  Artist - Title 3   already downloaded               # skipped
  ✗  https://…         HTTP Error 404                    # failed
```
File size (`3.2 MB`) comes from `total_bytes` captured in the progress hook.

### Summary
```python
console.print(Rule(style="dim"))
console.print(f"  [bold]{downloaded}[/] downloaded · [bold]{skipped}[/] skipped · [bold]{failed}[/] failed\n")
```
`Rule` is `from rich.rule import Rule`.

---

## Architecture Change: `progress_callback`

`download_track()` gets one new optional parameter:

```python
def download_track(url, output_dir, archive_path, allow_playlist=False, progress_callback=None):
```

Inside the progress hook:

```python
def progress_hook(d):
    if d['status'] == 'downloading' and progress_callback:
        progress_callback(
            downloaded_bytes=int(d.get('downloaded_bytes') or 0),
            total_bytes=d.get('total_bytes') or d.get('total_bytes_estimate'),
            filename=d.get('filename', ''),
        )
    if d['status'] == 'finished':
        downloaded_filename.append(d['filename'])
```

`download_track()` also returns `total_bytes` for the result line:

```python
# Return signature changes from:
return ('downloaded', mp3_path)
# To:
return ('downloaded', mp3_path, total_bytes_seen)
# Where total_bytes_seen is captured from the last 'downloading' hook call

# Skipped:
return ('skipped', None, None)

# Error:
return ('error', str(e), None)
```

### In `main()`

```python
for i, url in enumerate(urls):
    track_name = url  # fallback until filename known
    size_bytes = None

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task(f"  [{i+1}/{n}]  {_short_url(url)}", total=None)

        def on_progress(downloaded_bytes, total_bytes, filename):
            nonlocal track_name, size_bytes
            if filename:
                track_name = Path(filename).stem
                progress.update(task, description=f"  [{i+1}/{n}]  {track_name}")
            progress.update(task, completed=downloaded_bytes, total=total_bytes)
            size_bytes = total_bytes

        status, result, total = download_track(
            url, output_dir, archive_path, allow_playlist,
            progress_callback=on_progress,
        )

    # bar gone, print result line
    _print_result(status, result, track_name, total, trim_note)
```

### Helper functions

```python
def _short_url(url):
    """Shorten URL for display: keep last 2 path segments."""
    parts = url.rstrip('/').split('/')
    return '/'.join(parts[-2:]) if len(parts) >= 2 else url

def _format_bytes(n):
    """Format bytes as human-readable string."""
    if n is None:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
```

---

## Files Changed

- `soundklaut.py` only
  - New imports: `from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn, TextColumn` and `from rich.rule import Rule`
  - `download_track()` signature: add `progress_callback=None`, update return to 3-tuple
  - `main()`: add header, per-track Progress context, result printing, Rule + summary
  - Two small helpers: `_short_url()`, `_format_bytes()`

---

## Backward Compatibility

- `download_track()` return changes from 2-tuple to 3-tuple — all existing call sites in `main()` must be updated to unpack 3 values
- Tests that call `download_track()` directly must be updated to expect 3-tuple returns
- `progress_callback=None` default means tests that don't pass a callback continue to work

---

## Testing

- Update all existing `download_track` mock return values from 2-tuples to 3-tuples: `('downloaded', mp3, None)`, `('skipped', None, None)`, `('error', 'msg', None)`
- No new tests needed for the UI rendering itself (terminal output)
- One new test: `test_download_track_progress_callback_called` — verify callback is invoked when yt-dlp fires 'downloading' events
