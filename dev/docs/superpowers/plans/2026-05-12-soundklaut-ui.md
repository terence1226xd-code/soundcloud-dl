# soundklaut Rich UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace bare console.print output with a polished Rich terminal UI: styled header, per-track progress bar with speed/ETA, transient bar → result line, and a styled summary.

**Architecture:** Two tasks. Task 1 updates `download_track()` to accept an optional `progress_callback` and return a 3-tuple `(status, result, total_bytes)` — all tests updated to match. Task 2 rewrites `main()` using Rich Progress per track, adds two small helpers, and updates the Rich imports.

**Tech Stack:** Python 3.10+, rich.progress (Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn, TextColumn), existing yt-dlp/mutagen/pydub stack

---

### Task 1: Update `download_track()` — `progress_callback` + 3-tuple return

**Files:**
- Modify: `soundcloud-dl/soundklaut.py` (function signature, hook, return values)
- Modify: `soundcloud-dl/tests/test_soundklaut.py` (all 5 direct tests + 8 main mock returns)

- [ ] **Step 1: Write the failing progress_callback test**

Add this test to `tests/test_soundklaut.py` after `test_download_track_playlist_allowed`:

```python
@patch('soundklaut.yt_dlp.YoutubeDL')
def test_download_track_progress_callback_called(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'

    def factory(opts):
        cm = MagicMock()
        inner = MagicMock()

        def fake_download(urls):
            for hook in opts.get('progress_hooks', []):
                hook({
                    'status': 'downloading',
                    'downloaded_bytes': 512000,
                    'total_bytes': 1024000,
                    'filename': str(tmp_path / 'Artist - Title.webm'),
                })
                hook({
                    'status': 'finished',
                    'filename': str(tmp_path / 'Artist - Title.webm'),
                })
            return 0

        inner.download = fake_download
        cm.__enter__ = MagicMock(return_value=inner)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    mock_ydl.side_effect = factory

    calls = []
    def on_progress(downloaded_bytes, total_bytes, filename):
        calls.append((downloaded_bytes, total_bytes))

    status, path, total = download_track(
        'https://soundcloud.com/a/t', tmp_path, archive,
        progress_callback=on_progress,
    )

    assert status == 'downloaded'
    assert len(calls) == 1
    assert calls[0] == (512000, 1024000)
    assert total == 1024000
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/test_soundklaut.py::test_download_track_progress_callback_called -v
```
Expected: `FAILED` — `cannot unpack non-iterable` or `TypeError` because `download_track` still returns a 2-tuple

- [ ] **Step 3: Update `download_track()` in soundklaut.py**

Replace the entire `download_track` function with:

```python
def download_track(url, output_dir, archive_path, allow_playlist=False, progress_callback=None):
    downloaded_filename = []
    total_bytes_seen = [None]

    def progress_hook(d):
        if d['status'] == 'downloading' and progress_callback:
            downloaded = int(d.get('downloaded_bytes') or 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            total_bytes_seen[0] = total
            progress_callback(
                downloaded_bytes=downloaded,
                total_bytes=total,
                filename=d.get('filename', ''),
            )
        if d['status'] == 'finished':
            downloaded_filename.append(d['filename'])

    opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
        'outtmpl': str(output_dir / '%(uploader)s - %(title)s.%(ext)s'),
        'download_archive': str(archive_path),
        'writeinfojson': True,
        'noplaylist': not allow_playlist,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        return ('error', str(e), None)

    if not downloaded_filename:
        return ('skipped', None, None)

    mp3_path = Path(downloaded_filename[0]).with_suffix('.mp3')
    return ('downloaded', mp3_path, total_bytes_seen[0])
```

- [ ] **Step 4: Update the 3 direct download_track tests to unpack 3-tuple**

In `tests/test_soundklaut.py`, find and update these three tests:

```python
# test_download_track_downloaded — change unpacking:
status, path, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)
assert status == 'downloaded'
assert path == tmp_path / 'Artist - Title.mp3'

# test_download_track_skipped — change unpacking:
status, path, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)
assert status == 'skipped'
assert path is None

# test_download_track_error — change unpacking:
status, msg, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)
assert status == 'error'
assert '404' in msg
```

(`test_download_track_no_playlist_by_default` and `test_download_track_playlist_allowed` do not capture the return value — leave them unchanged.)

- [ ] **Step 5: Update all `main()` mock return values to 3-tuples**

In `tests/test_soundklaut.py`, find every `mock_download_track.return_value = (...)` and `mock_download_track.side_effect = [...]` and update each:

```python
# test_main_calls_set_metadata_on_download
mock_download_track.return_value = ('downloaded', mp3, None)

# test_main_skipped_does_not_call_set_metadata
mock_download_track.return_value = ('skipped', None, None)

# test_main_all_failed_exits_one
mock_download_track.return_value = ('error', 'HTTP 404', None)

# test_main_partial_failure_exits_zero
mock_download_track.side_effect = [
    ('downloaded', mp3, None),
    ('error', 'HTTP 404', None),
]

# test_main_trim_called_with_defaults
mock_download_track.return_value = ('downloaded', mp3, None)

# test_main_no_trim_flag_skips_trim
mock_download_track.return_value = ('downloaded', mp3, None)

# test_main_custom_silence_threshold
mock_download_track.return_value = ('downloaded', mp3, None)

# test_main_trim_exception_does_not_crash
mock_download_track.return_value = ('downloaded', mp3, None)
```

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -v
```
Expected: `27 passed` (26 previous + 1 new callback test)

- [ ] **Step 7: Commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add soundklaut.py tests/test_soundklaut.py
git commit -m "feat: add progress_callback to download_track, return 3-tuple"
```

---

### Task 2: Rewrite `main()` with Rich Progress UI

**Files:**
- Modify: `soundcloud-dl/soundklaut.py` (imports, helpers, main rewrite)

- [ ] **Step 1: Update the Rich import in soundklaut.py**

The current import is:
```python
from rich.console import Console
```

Replace it with:
```python
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
```

- [ ] **Step 2: Run existing tests to confirm imports don't break anything**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -q 2>&1 | tail -3
```
Expected: `27 passed`

- [ ] **Step 3: Add helpers before `main()`**

Insert these two functions immediately before `def main():`:

```python
def _short_url(url):
    parts = url.rstrip('/').split('/')
    return '/'.join(parts[-2:]) if len(parts) >= 2 else url


def _format_bytes(n):
    if n is None:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} GB'
```

- [ ] **Step 4: Replace `main()` with the Rich UI version**

Replace the entire `main()` function with:

```python
def main():
    parser = argparse.ArgumentParser(
        description='Download SoundCloud tracks as MP3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  %(prog)s https://soundcloud.com/artist/track\n'
            '  %(prog)s url1 url2 --output ~/Music\n'
            '  %(prog)s --playlist https://soundcloud.com/artist/sets/name\n'
            '  %(prog)s <url> --no-trim\n'
            '  %(prog)s <url> --silence-threshold -40'
        ),
    )
    parser.add_argument('urls', nargs='*', metavar='URL', help='SoundCloud track URL(s)')
    parser.add_argument('--playlist', metavar='URL', help='SoundCloud playlist URL')
    parser.add_argument('--output', '-o', metavar='DIR', default='downloads',
                        help='Output directory (default: downloads)')
    parser.add_argument('--no-trim', action='store_true',
                        help='Disable trailing silence trimming')
    parser.add_argument('--silence-threshold', type=float, default=-50.0, metavar='DB',
                        help='Silence threshold in dBFS (default: -50)')
    args = parser.parse_args()

    urls = build_urls(args)
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / 'downloaded.txt'
    allow_playlist = args.playlist is not None
    n = len(urls)

    console.print(
        f"\n [bold cyan]soundklaut[/]  ·  "
        f"{n} track{'s' if n != 1 else ''}  →  [dim]{output_dir}[/]\n"
    )

    downloaded = skipped = failed = 0

    for i, url in enumerate(urls):
        track_name = _short_url(url)
        file_size = None

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
            task = progress.add_task(
                f"  [{i + 1}/{n}]  {track_name}", total=None
            )

            def on_progress(downloaded_bytes, total_bytes, filename,
                            _task=task, _progress=progress, _idx=i):
                nonlocal track_name, file_size
                if filename:
                    name = Path(filename).stem
                    if name != track_name:
                        track_name = name
                        _progress.update(
                            _task,
                            description=f"  [{_idx + 1}/{n}]  {track_name}",
                        )
                _progress.update(_task, completed=downloaded_bytes, total=total_bytes)
                file_size = total_bytes

            status, result, total = download_track(
                url, output_dir, archive_path, allow_playlist,
                progress_callback=on_progress,
            )

        if status == 'downloaded':
            trim_note = ''
            if not args.no_trim:
                try:
                    trimmed, secs = trim_trailing_silence(
                        result,
                        silence_thresh=args.silence_threshold,
                        min_silence_len=2000,
                    )
                    if trimmed:
                        trim_note = f'  [dim](trimmed {secs:.1f}s)[/]'
                except Exception as e:
                    console.print(f"  [yellow]⚠[/]  trim failed: {e}")

            info_json = result.with_suffix('.info.json')
            if info_json.exists():
                try:
                    set_metadata(result, info_json)
                except Exception as e:
                    console.print(
                        f"  [yellow]⚠[/]  {result.stem}  [dim](metadata failed: {e})[/]"
                    )

            size_str = (
                f'  [dim]{_format_bytes(total or file_size)}[/]'
                if (total or file_size) else ''
            )
            console.print(f"  [green]✓[/]  {track_name}{trim_note}{size_str}")
            downloaded += 1

        elif status == 'skipped':
            console.print(
                f"  [yellow]⏭[/]  {track_name}  [dim]already downloaded[/]"
            )
            skipped += 1

        else:
            console.print(f"  [red]✗[/]  {track_name}  [dim]{result}[/]")
            failed += 1

    console.print()
    console.rule(style='dim')
    console.print(
        f"  [bold]{downloaded}[/] downloaded · "
        f"[bold]{skipped}[/] skipped · "
        f"[bold]{failed}[/] failed\n"
    )

    if downloaded == 0 and failed > 0:
        sys.exit(1)
```

**Note on the `on_progress` default-argument trick:** `def on_progress(..., _task=task, _progress=progress, _idx=i)` captures the loop-local values of `task`, `progress`, and `i` via default arguments — this avoids the classic Python late-binding closure bug where all iterations share the same variable.

- [ ] **Step 5: Run the full test suite**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -v
```
Expected: `27 passed`

- [ ] **Step 6: Smoke-test the UI manually (optional but recommended)**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 soundklaut.py --help
```
Expected: help text with `--no-trim`, `--silence-threshold` visible.

- [ ] **Step 7: Commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add soundklaut.py
git commit -m "feat: Rich progress bar UI with header, speed, ETA, and styled summary"
```

---

## Self-Review

**Spec coverage:**
- ✓ Header line: `soundklaut · N tracks → /path`
- ✓ Per-track progress bar: SpinnerColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn
- ✓ `transient=True` — bar disappears after download
- ✓ Track name updated from `d['filename']` during first downloading event
- ✓ Indeterminate bar when `total_bytes` is None (Progress handles this automatically when `total=None`)
- ✓ Result lines: ✓ with size, ✓ with trim note, ⏭ already downloaded, ✗ with error
- ✓ `console.rule()` separator + styled summary
- ✓ `_short_url()` helper
- ✓ `_format_bytes()` helper
- ✓ `progress_callback=None` backward compatible
- ✓ 3-tuple return: `('downloaded', Path, total_bytes)` | `('skipped', None, None)` | `('error', str, None)`
- ✓ All existing tests updated to 3-tuple mock returns
- ✓ One new test: `test_download_track_progress_callback_called`

**Placeholder scan:** None.

**Type consistency:** `progress_callback(downloaded_bytes, total_bytes, filename)` defined in Task 1 hook, called identically in Task 2 `on_progress`. `total` from 3-tuple consumed as `_format_bytes(total or file_size)` in Task 2. ✓
