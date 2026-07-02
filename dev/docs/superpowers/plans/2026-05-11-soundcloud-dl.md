# SoundCloud Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that downloads SoundCloud tracks/playlists as ID3-tagged MP3 files, skipping already-downloaded tracks via yt-dlp's download archive.

**Architecture:** Single-file Python script (`soundcloud_dl.py`). `download_track()` wraps yt-dlp's Python API with progress hooks to detect skip vs. download. `set_metadata()` reads yt-dlp's `.info.json`, writes ID3 tags via mutagen, then deletes the JSON. `main()` drives the loop with Rich console output and a final summary.

**Tech Stack:** Python 3.10+, yt-dlp, mutagen, Rich, pytest, FFmpeg (system dependency)

---

### Task 1: Project Scaffold

**Files:**
- Create: `soundcloud-dl/soundcloud_dl.py`
- Create: `soundcloud-dl/requirements.txt`
- Create: `soundcloud-dl/tests/__init__.py`
- Create: `soundcloud-dl/tests/test_soundcloud_dl.py`

- [ ] **Step 1: Create project directories**

```bash
mkdir -p soundcloud-dl/downloads soundcloud-dl/tests
```

- [ ] **Step 2: Create requirements.txt**

```
yt-dlp>=2024.1.1
mutagen>=1.47.0
rich>=13.7.0
pytest>=8.0.0
```

- [ ] **Step 3: Create soundcloud_dl.py with imports only**

```python
import argparse
import json
import sys
from pathlib import Path

import yt_dlp
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from rich.console import Console

console = Console()
```

- [ ] **Step 4: Create tests/test_soundcloud_dl.py scaffold**

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from soundcloud_dl import build_urls, download_track, set_metadata
```

- [ ] **Step 5: Create tests/__init__.py**

```bash
touch soundcloud-dl/tests/__init__.py
```

- [ ] **Step 6: Install dependencies**

```bash
cd soundcloud-dl && pip install -r requirements.txt
```

- [ ] **Step 7: Verify imports work**

```bash
cd soundcloud-dl && python -c "import yt_dlp, mutagen, rich; print('OK')"
```
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
cd soundcloud-dl && git init && git add . && git commit -m "feat: scaffold soundcloud-dl project"
```

---

### Task 2: `build_urls(args)`

Normalises argparse Namespace into a flat list of URLs.

**Files:**
- Modify: `soundcloud-dl/soundcloud_dl.py`
- Modify: `soundcloud-dl/tests/test_soundcloud_dl.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_soundcloud_dl.py`:

```python
def make_args(**kwargs):
    defaults = {'urls': [], 'playlist': None, 'output': 'downloads'}
    defaults.update(kwargs)
    return type('Args', (), defaults)()


def test_build_urls_single():
    args = make_args(urls=['https://soundcloud.com/artist/track'])
    assert build_urls(args) == ['https://soundcloud.com/artist/track']


def test_build_urls_multiple():
    args = make_args(urls=['https://soundcloud.com/a/1', 'https://soundcloud.com/a/2'])
    assert build_urls(args) == ['https://soundcloud.com/a/1', 'https://soundcloud.com/a/2']


def test_build_urls_playlist():
    args = make_args(urls=[], playlist='https://soundcloud.com/artist/sets/my-set')
    assert build_urls(args) == ['https://soundcloud.com/artist/sets/my-set']


def test_build_urls_empty_raises():
    args = make_args(urls=[], playlist=None)
    with pytest.raises(SystemExit):
        build_urls(args)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "build_urls" -v
```
Expected: `ImportError: cannot import name 'build_urls'`

- [ ] **Step 3: Implement build_urls**

Add to `soundcloud_dl.py`:

```python
def build_urls(args):
    urls = list(args.urls or [])
    if args.playlist:
        urls.append(args.playlist)
    if not urls:
        console.print("[red]Error: provide at least one URL or --playlist[/]")
        sys.exit(1)
    return urls
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "build_urls" -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd soundcloud-dl && git add soundcloud_dl.py tests/test_soundcloud_dl.py
git commit -m "feat: add build_urls with tests"
```

---

### Task 3: `set_metadata(mp3_path, info_json_path)`

Reads yt-dlp's `.info.json`, writes ID3 tags (title, artist, album, year), deletes JSON.

**Files:**
- Modify: `soundcloud-dl/soundcloud_dl.py`
- Modify: `soundcloud-dl/tests/test_soundcloud_dl.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_soundcloud_dl.py`:

```python
from mutagen.id3 import ID3


def test_set_metadata_writes_tags(tmp_path):
    mp3 = tmp_path / "Artist - Title.mp3"
    mp3.write_bytes(b'')  # mutagen writes ID3 header onto any file

    info_json = tmp_path / "Artist - Title.info.json"
    info_json.write_text(json.dumps({
        'title': 'My Song',
        'uploader': 'My Artist',
        'upload_date': '20240315',
    }))

    set_metadata(mp3, info_json)

    tags = ID3(mp3)
    assert str(tags['TIT2']) == 'My Song'
    assert str(tags['TPE1']) == 'My Artist'
    assert str(tags['TALB']) == 'My Artist'
    assert str(tags['TDRC']) == '2024'


def test_set_metadata_deletes_json(tmp_path):
    mp3 = tmp_path / "Artist - Title.mp3"
    mp3.write_bytes(b'')

    info_json = tmp_path / "Artist - Title.info.json"
    info_json.write_text(json.dumps({'title': 'T', 'uploader': 'A', 'upload_date': '20200101'}))

    set_metadata(mp3, info_json)

    assert not info_json.exists()


def test_set_metadata_missing_upload_date(tmp_path):
    mp3 = tmp_path / "Artist - Title.mp3"
    mp3.write_bytes(b'')

    info_json = tmp_path / "Artist - Title.info.json"
    info_json.write_text(json.dumps({'title': 'T', 'uploader': 'A'}))

    set_metadata(mp3, info_json)  # must not raise

    tags = ID3(mp3)
    assert 'TDRC' not in tags
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "set_metadata" -v
```
Expected: `ImportError: cannot import name 'set_metadata'`

- [ ] **Step 3: Implement set_metadata**

Add to `soundcloud_dl.py`:

```python
def set_metadata(mp3_path, info_json_path):
    with open(info_json_path) as f:
        info = json.load(f)

    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags['TIT2'] = TIT2(encoding=3, text=info.get('title', ''))
    tags['TPE1'] = TPE1(encoding=3, text=info.get('uploader', ''))
    tags['TALB'] = TALB(encoding=3, text=info.get('uploader', ''))
    if info.get('upload_date'):
        tags['TDRC'] = TDRC(encoding=3, text=info['upload_date'][:4])

    tags.save(mp3_path)
    Path(info_json_path).unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "set_metadata" -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd soundcloud-dl && git add soundcloud_dl.py tests/test_soundcloud_dl.py
git commit -m "feat: add set_metadata with ID3 tagging and tests"
```

---

### Task 4: `download_track(url, output_dir, archive_path, allow_playlist=False)`

Wraps yt-dlp. Uses a progress hook to distinguish downloaded vs. skipped.
Returns `('downloaded', Path)` | `('skipped', None)` | `('error', str)`.

**Files:**
- Modify: `soundcloud-dl/soundcloud_dl.py`
- Modify: `soundcloud-dl/tests/test_soundcloud_dl.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_soundcloud_dl.py`:

```python
def _make_ydl_mock(hook_payloads=None, raises=None):
    """
    Returns a side_effect for yt_dlp.YoutubeDL that:
    - fires progress_hooks with hook_payloads during download(), or
    - raises `raises` from download() if provided.
    """
    def factory(opts):
        cm = MagicMock()
        inner = MagicMock()

        def fake_enter():
            if hook_payloads is not None:
                for payload in hook_payloads:
                    for hook in opts.get('progress_hooks', []):
                        hook(payload)
            return inner

        def fake_download(urls):
            if raises:
                raise raises
            return 0

        inner.download = fake_download
        cm.__enter__ = MagicMock(side_effect=lambda: fake_enter())
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return factory


@patch('soundcloud_dl.yt_dlp.YoutubeDL')
def test_download_track_downloaded(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    payload = {'status': 'finished', 'filename': str(tmp_path / 'Artist - Title.webm')}
    mock_ydl.side_effect = _make_ydl_mock(hook_payloads=[payload])

    status, path = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'downloaded'
    assert path == tmp_path / 'Artist - Title.mp3'


@patch('soundcloud_dl.yt_dlp.YoutubeDL')
def test_download_track_skipped(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    mock_ydl.side_effect = _make_ydl_mock(hook_payloads=[])  # no hooks fired = skipped

    status, path = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'skipped'
    assert path is None


@patch('soundcloud_dl.yt_dlp.YoutubeDL')
def test_download_track_error(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    mock_ydl.side_effect = _make_ydl_mock(
        raises=yt_dlp.utils.DownloadError('404 Not Found')
    )

    status, msg = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'error'
    assert '404' in msg


@patch('soundcloud_dl.yt_dlp.YoutubeDL')
def test_download_track_no_playlist_by_default(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    captured = {}

    def capture(opts):
        captured.update(opts)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=MagicMock(download=MagicMock(return_value=0)))
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    mock_ydl.side_effect = capture
    download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert captured.get('noplaylist') is True


@patch('soundcloud_dl.yt_dlp.YoutubeDL')
def test_download_track_playlist_allowed(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    captured = {}

    def capture(opts):
        captured.update(opts)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=MagicMock(download=MagicMock(return_value=0)))
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    mock_ydl.side_effect = capture
    download_track('https://soundcloud.com/a/t', tmp_path, archive, allow_playlist=True)

    assert captured.get('noplaylist') is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "download_track" -v
```
Expected: `ImportError: cannot import name 'download_track'`

- [ ] **Step 3: Implement download_track**

Add to `soundcloud_dl.py`:

```python
def download_track(url, output_dir, archive_path, allow_playlist=False):
    downloaded_filename = []

    def progress_hook(d):
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
        return ('error', str(e))

    if not downloaded_filename:
        return ('skipped', None)

    mp3_path = Path(downloaded_filename[0]).with_suffix('.mp3')
    return ('downloaded', mp3_path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "download_track" -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd soundcloud-dl && git add soundcloud_dl.py tests/test_soundcloud_dl.py
git commit -m "feat: add download_track with yt-dlp integration and tests"
```

---

### Task 5: `main()` — CLI + Rich output

Wires argparse, the download loop, `set_metadata`, and Rich console output.

**Files:**
- Modify: `soundcloud-dl/soundcloud_dl.py`
- Modify: `soundcloud-dl/tests/test_soundcloud_dl.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_soundcloud_dl.py`:

```python
@patch('soundcloud_dl.download_track')
@patch('soundcloud_dl.set_metadata')
def test_main_calls_set_metadata_on_download(mock_set_metadata, mock_download_track, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    info_json = mp3.with_suffix('.info.json')
    info_json.write_text('{}')

    mock_download_track.return_value = ('downloaded', mp3)

    with patch('sys.argv', ['soundcloud_dl.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        from soundcloud_dl import main
        main()

    mock_set_metadata.assert_called_once_with(mp3, mp3.with_suffix('.info.json'))


@patch('soundcloud_dl.download_track')
@patch('soundcloud_dl.set_metadata')
def test_main_skipped_does_not_call_set_metadata(mock_set_metadata, mock_download_track, tmp_path):
    mock_download_track.return_value = ('skipped', None)

    with patch('sys.argv', ['soundcloud_dl.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        from soundcloud_dl import main
        main()

    mock_set_metadata.assert_not_called()


@patch('soundcloud_dl.download_track')
def test_main_all_failed_exits_one(mock_download_track, tmp_path):
    mock_download_track.return_value = ('error', 'HTTP 404')

    with patch('sys.argv', ['soundcloud_dl.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        from soundcloud_dl import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


@patch('soundcloud_dl.download_track')
@patch('soundcloud_dl.set_metadata')
def test_main_partial_failure_exits_zero(mock_set_metadata, mock_download_track, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')

    mock_download_track.side_effect = [
        ('downloaded', mp3),
        ('error', 'HTTP 404'),
    ]

    with patch('sys.argv', ['soundcloud_dl.py',
                            'https://soundcloud.com/a/1',
                            'https://soundcloud.com/a/2',
                            '--output', str(tmp_path)]):
        from soundcloud_dl import main
        main()  # must not raise — partial success = exit 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd soundcloud-dl && python -m pytest tests/test_soundcloud_dl.py -k "test_main" -v
```
Expected: `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement main()**

Add to `soundcloud_dl.py`:

```python
def main():
    parser = argparse.ArgumentParser(
        description='Download SoundCloud tracks as MP3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  %(prog)s https://soundcloud.com/artist/track\n'
            '  %(prog)s url1 url2 --output ~/Music\n'
            '  %(prog)s --playlist https://soundcloud.com/artist/sets/name'
        ),
    )
    parser.add_argument('urls', nargs='*', metavar='URL', help='SoundCloud track URL(s)')
    parser.add_argument('--playlist', metavar='URL', help='SoundCloud playlist URL')
    parser.add_argument('--output', '-o', metavar='DIR', default='downloads',
                        help='Output directory (default: downloads)')
    args = parser.parse_args()

    urls = build_urls(args)
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / 'downloaded.txt'
    allow_playlist = args.playlist is not None

    downloaded = skipped = failed = 0

    console.print(f"[bold]Downloading {len(urls)} URL(s) → {output_dir}[/]\n")

    for url in urls:
        status, result = download_track(url, output_dir, archive_path, allow_playlist)

        if status == 'downloaded':
            info_json = result.with_suffix('.info.json')
            if info_json.exists():
                set_metadata(result, info_json)
            console.print(f"  [green]✓[/] {result.stem}")
            downloaded += 1
        elif status == 'skipped':
            console.print(f"  [yellow]⏭[/] {url}  [dim](already downloaded)[/]")
            skipped += 1
        else:
            console.print(f"  [red]✗[/] {url}  [dim]{result}[/]")
            failed += 1

    console.print(
        f"\n[bold]Done:[/] {downloaded} downloaded, {skipped} skipped, {failed} failed"
    )

    if downloaded == 0 and failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run full test suite**

```bash
cd soundcloud-dl && python -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 5: Smoke test (requires network + ffmpeg)**

```bash
cd soundcloud-dl && python soundcloud_dl.py https://soundcloud.com/forss/flickermood
```
Expected: MP3 in `downloads/`, second run prints `⏭ already downloaded`.

- [ ] **Step 6: Final commit**

```bash
cd soundcloud-dl && git add soundcloud_dl.py tests/test_soundcloud_dl.py
git commit -m "feat: add main() with argparse and Rich CLI output"
```

---

## Self-Review

**Spec coverage:**
- ✓ Single/multiple track URLs → `build_urls` + `main` loop
- ✓ `--playlist` flag → `allow_playlist=True`, `noplaylist: False` in yt-dlp opts
- ✓ `--output` / `-o` flag → `output_dir` in `main`
- ✓ Best audio quality → `bestaudio/best` + `preferredquality: '0'`
- ✓ Duplicate detection → `--download-archive downloaded.txt`
- ✓ ID3 tags (title, artist) from `.info.json` → `set_metadata`
- ✓ `.info.json` cleanup → `Path(info_json_path).unlink()`
- ✓ Per-track error handling, loop continues → try/except in `download_track`
- ✓ Rich CLI output → `console.print` with markup
- ✓ Final summary → `downloaded / skipped / failed` counts
- ✓ Exit code 1 only when all tracks failed → `if downloaded == 0 and failed > 0`

**Placeholder scan:** None found.

**Type consistency:** Return tuple `('downloaded', Path)` | `('skipped', None)` | `('error', str)` defined in Task 4 and consumed identically in Task 5. ✓
