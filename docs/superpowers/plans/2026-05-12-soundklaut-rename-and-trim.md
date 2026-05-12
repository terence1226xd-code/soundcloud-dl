# soundklaut Rename + Trailing Silence Trim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project to `soundklaut` and add automatic trailing-silence trimming with configurable CLI flags.

**Architecture:** Task 1 is a mechanical rename with no logic changes. Task 2 adds `trim_trailing_silence()` as an isolated pure function tested with real pydub audio. Task 3 wires the function into `main()` behind `--no-trim` / `--silence-threshold` flags.

**Tech Stack:** Python 3.10+, pydub, mutagen, yt-dlp, Rich, pytest — plus FFmpeg (already required)

---

### Task 1: Rename `soundcloud_dl` → `soundklaut`

**Files:**
- Rename: `soundcloud-dl/soundcloud_dl.py` → `soundcloud-dl/soundklaut.py`
- Rename: `soundcloud-dl/tests/test_soundcloud_dl.py` → `soundcloud-dl/tests/test_soundklaut.py`
- Modify: `soundcloud-dl/tests/test_soundklaut.py` (string replacements)

- [ ] **Step 1: Confirm tests pass before touching anything**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -q
```
Expected: `16 passed`

- [ ] **Step 2: Rename the main script**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && mv soundcloud_dl.py soundklaut.py
```

- [ ] **Step 3: Rename the test file**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && mv tests/test_soundcloud_dl.py tests/test_soundklaut.py
```

- [ ] **Step 4: Update all string references in the test file**

Replace every occurrence of `soundcloud_dl` with `soundklaut` in `tests/test_soundklaut.py`:

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && sed -i '' 's/soundcloud_dl/soundklaut/g' tests/test_soundklaut.py
```

This covers:
- `from soundcloud_dl import …` → `from soundklaut import …`
- `@patch('soundcloud_dl.*')` → `@patch('soundklaut.*')`
- `sys.argv` entries `'soundcloud_dl.py'` → `'soundklaut.py'`

- [ ] **Step 5: Verify the replacement is correct**

```bash
grep -n "soundcloud_dl" /Users/romangerdes/Documents/Privat/Music/soundcloud-dl/tests/test_soundklaut.py
```
Expected: no output (zero occurrences remain)

- [ ] **Step 6: Run the full test suite**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -v
```
Expected: `16 passed`

- [ ] **Step 7: Commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add -A && git commit -m "refactor: rename soundcloud_dl to soundklaut"
```

---

### Task 2: `trim_trailing_silence(mp3_path, silence_thresh=-50, min_silence_len=2000)`

Isolated function. Uses pydub to detect and remove trailing silence from an MP3 file in-place. Tested with synthetic audio.

**Files:**
- Modify: `soundcloud-dl/soundklaut.py` (add imports + function)
- Modify: `soundcloud-dl/requirements.txt` (add pydub)
- Modify: `soundcloud-dl/tests/test_soundklaut.py` (add unit tests)

- [ ] **Step 1: Add pydub to requirements.txt**

Open `soundcloud-dl/requirements.txt` and add:
```
pydub>=0.25.1
```

Then install:
```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && pip3 install pydub
```

- [ ] **Step 2: Write failing tests**

Add to the END of `tests/test_soundklaut.py`:

```python
from pydub import AudioSegment
from pydub.generators import Sine

from soundklaut import trim_trailing_silence


def _make_test_mp3(path, tone_ms=3000, silence_ms=0):
    """Create a real MP3: sine tone followed by optional silence."""
    audio = Sine(440).to_audio_segment(duration=tone_ms)
    if silence_ms > 0:
        audio = audio + AudioSegment.silent(duration=silence_ms)
    audio.export(path, format='mp3', bitrate='128k')


def test_trim_long_trailing_silence(tmp_path):
    mp3 = tmp_path / 'track.mp3'
    _make_test_mp3(mp3, tone_ms=3000, silence_ms=3000)

    trimmed, secs = trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    assert trimmed is True
    assert 2.5 <= secs <= 4.0  # ~3s; MP3 frame alignment allows small variance


def test_trim_short_trailing_silence_not_trimmed(tmp_path):
    mp3 = tmp_path / 'track.mp3'
    _make_test_mp3(mp3, tone_ms=3000, silence_ms=500)  # 500ms < min_silence_len

    trimmed, secs = trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    assert trimmed is False
    assert secs == 0.0


def test_trim_no_silence_not_trimmed(tmp_path):
    mp3 = tmp_path / 'track.mp3'
    _make_test_mp3(mp3, tone_ms=3000, silence_ms=0)

    trimmed, secs = trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    assert trimmed is False
    assert secs == 0.0


def test_trim_middle_silence_not_trimmed(tmp_path):
    """Silence in the middle should NOT be trimmed — track ends with a tone."""
    mp3 = tmp_path / 'track.mp3'
    tone1 = Sine(440).to_audio_segment(duration=2000)
    silence = AudioSegment.silent(duration=3000)
    tone2 = Sine(440).to_audio_segment(duration=2000)
    (tone1 + silence + tone2).export(mp3, format='mp3', bitrate='128k')

    trimmed, secs = trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    assert trimmed is False


def test_trim_preserves_bitrate(tmp_path):
    """After trimming, the file is re-exported with the original bitrate."""
    from mutagen.mp3 import MP3 as MutagenMP3
    mp3 = tmp_path / 'track.mp3'
    _make_test_mp3(mp3, tone_ms=3000, silence_ms=3000)
    original_bitrate = MutagenMP3(mp3).info.bitrate // 1000

    trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    new_bitrate = MutagenMP3(mp3).info.bitrate // 1000
    assert new_bitrate == original_bitrate


def test_trim_file_shorter_after_trim(tmp_path):
    """Trimmed file must be shorter than the original."""
    mp3 = tmp_path / 'track.mp3'
    _make_test_mp3(mp3, tone_ms=3000, silence_ms=3000)
    original_len = len(AudioSegment.from_mp3(mp3))

    trim_trailing_silence(mp3, silence_thresh=-50, min_silence_len=2000)

    new_len = len(AudioSegment.from_mp3(mp3))
    assert new_len < original_len
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/test_soundklaut.py -k "trim" -v
```
Expected: `ImportError: cannot import name 'trim_trailing_silence'`

- [ ] **Step 4: Add imports to soundklaut.py**

Open `soundklaut.py`. The current import block is:

```python
import argparse
import json
import sys
from pathlib import Path

import yt_dlp
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from rich.console import Console
```

Replace it with:

```python
import argparse
import json
import sys
from pathlib import Path

import yt_dlp
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from mutagen.mp3 import MP3 as MutagenMP3
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from rich.console import Console
```

- [ ] **Step 5: Implement trim_trailing_silence**

Add this function to `soundklaut.py` after `set_metadata` and before `download_track`:

```python
def trim_trailing_silence(mp3_path, silence_thresh=-50, min_silence_len=2000):
    audio = AudioSegment.from_mp3(mp3_path)

    trim_ms = detect_leading_silence(
        audio.reverse(),
        silence_threshold=silence_thresh,
        chunk_size=10,
    )

    if trim_ms < min_silence_len or trim_ms >= len(audio):
        return (False, 0.0)

    try:
        bitrate = MutagenMP3(mp3_path).info.bitrate // 1000
    except Exception:
        bitrate = 192

    trimmed = audio[:-trim_ms]
    trimmed.export(mp3_path, format='mp3', bitrate=f'{bitrate}k')
    return (True, trim_ms / 1000.0)
```

- [ ] **Step 6: Run trim tests to verify they pass**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/test_soundklaut.py -k "trim" -v
```
Expected: `6 passed`

- [ ] **Step 7: Run full suite to check for regressions**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -v
```
Expected: `22 passed`

- [ ] **Step 8: Commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add soundklaut.py requirements.txt tests/test_soundklaut.py
git commit -m "feat: add trim_trailing_silence with pydub and tests"
```

---

### Task 3: Wire `trim_trailing_silence` into `main()` + CLI flags

**Files:**
- Modify: `soundcloud-dl/soundklaut.py` (update `main()`)
- Modify: `soundcloud-dl/tests/test_soundklaut.py` (add integration tests)

- [ ] **Step 1: Write failing integration tests**

Add to the END of `tests/test_soundklaut.py`:

```python
@patch('soundklaut.trim_trailing_silence')
@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_trim_called_with_defaults(mock_set_metadata, mock_download_track, mock_trim, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')
    mock_download_track.return_value = ('downloaded', mp3)
    mock_trim.return_value = (False, 0.0)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        main()

    mock_trim.assert_called_once_with(mp3, silence_thresh=-50.0, min_silence_len=2000)


@patch('soundklaut.trim_trailing_silence')
@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_no_trim_flag_skips_trim(mock_set_metadata, mock_download_track, mock_trim, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')
    mock_download_track.return_value = ('downloaded', mp3)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path), '--no-trim']):
        main()

    mock_trim.assert_not_called()


@patch('soundklaut.trim_trailing_silence')
@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_custom_silence_threshold(mock_set_metadata, mock_download_track, mock_trim, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')
    mock_download_track.return_value = ('downloaded', mp3)
    mock_trim.return_value = (False, 0.0)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path), '--silence-threshold', '-40']):
        main()

    mock_trim.assert_called_once_with(mp3, silence_thresh=-40.0, min_silence_len=2000)


@patch('soundklaut.trim_trailing_silence')
@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_trim_exception_does_not_crash(mock_set_metadata, mock_download_track, mock_trim, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')
    mock_download_track.return_value = ('downloaded', mp3)
    mock_trim.side_effect = Exception('pydub decode error')

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        main()  # must not raise; track still counts as downloaded
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/test_soundklaut.py -k "test_main_trim or test_main_no_trim or test_main_custom" -v
```
Expected: all fail — `main()` doesn't have `--no-trim` or `--silence-threshold` yet

- [ ] **Step 3: Update main() in soundklaut.py**

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

    downloaded = skipped = failed = 0

    console.print(f"[bold]Downloading {len(urls)} URL(s) → {output_dir}[/]\n")

    for url in urls:
        status, result = download_track(url, output_dir, archive_path, allow_playlist)

        if status == 'downloaded':
            info_json = result.with_suffix('.info.json')

            trim_note = ''
            if not args.no_trim:
                try:
                    trimmed, secs = trim_trailing_silence(
                        result,
                        silence_thresh=args.silence_threshold,
                        min_silence_len=2000,
                    )
                    if trimmed:
                        trim_note = f' [dim](trimmed {secs:.1f}s silence)[/]'
                except Exception as e:
                    console.print(f"  [yellow]⚠[/] trim failed: {e}")

            if info_json.exists():
                try:
                    set_metadata(result, info_json)
                except Exception as e:
                    console.print(f"  [yellow]⚠[/] {result.stem}  [dim](metadata failed: {e})[/]")

            console.print(f"  [green]✓[/] {result.stem}{trim_note}")
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
```

- [ ] **Step 4: Run new integration tests**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/test_soundklaut.py -k "test_main_trim or test_main_no_trim or test_main_custom" -v
```
Expected: `4 passed`

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && python3 -m pytest tests/ -v
```
Expected: `26 passed` (16 original + 6 trim unit + 4 main integration)

- [ ] **Step 6: Final commit**

```bash
cd /Users/romangerdes/Documents/Privat/Music/soundcloud-dl && git add soundklaut.py tests/test_soundklaut.py
git commit -m "feat: wire trim_trailing_silence into main with --no-trim and --silence-threshold flags"
```

---

## Self-Review

**Spec coverage:**
- ✓ Rename `soundcloud_dl` → `soundklaut` everywhere
- ✓ `trim_trailing_silence(mp3_path, silence_thresh, min_silence_len)` 
- ✓ `detect_leading_silence` on `audio.reverse()` (not `detect_silence`)
- ✓ `bitrate = MutagenMP3(mp3_path).info.bitrate // 1000` (bits/sec → kbps)
- ✓ Fallback 192k if bitrate unreadable
- ✓ Non-destructive: file untouched if `trim_ms < min_silence_len`
- ✓ Guard: `trim_ms >= len(audio)` → (False, 0.0) — prevents empty export
- ✓ Returns `(True, seconds_removed)` | `(False, 0.0)`
- ✓ Integration: trim after download, before set_metadata
- ✓ `--no-trim` flag
- ✓ `--silence-threshold` flag (float, default -50.0)
- ✓ CLI output: `✓ Track Name (trimmed 3.2s silence)`
- ✓ pydub in requirements.txt
- ✓ Archive file left unchanged (no rename needed)

**Placeholder scan:** None.

**Type consistency:** `trim_trailing_silence` returns `(bool, float)` in Task 2; consumed as `(trimmed, secs)` in Task 3. ✓ `silence_thresh` param name consistent throughout. ✓
