# soundklaut — Rename + Trailing Silence Trim
_Date: 2026-05-12_

## Overview

Two independent changes to the SoundCloud downloader:

1. **Rename** — `soundcloud_dl` → `soundklaut` across all files
2. **Trim** — add `trim_trailing_silence()` to automatically remove silence at the end of downloaded MP3s

---

## Part 1: Rename

### Files changed

| From | To |
|---|---|
| `soundcloud_dl.py` | `soundklaut.py` |
| `tests/test_soundcloud_dl.py` | `tests/test_soundklaut.py` |

### String replacements in `tests/test_soundklaut.py`

- `from soundcloud_dl import …` → `from soundklaut import …`
- All `@patch('soundcloud_dl.*')` decorators → `@patch('soundklaut.*')`
- All `sys.argv` entries `'soundcloud_dl.py'` → `'soundklaut.py'`

### Not changed

- Archive file `downloads/downloaded.txt` — name stays as-is
- No `setup.py` / `pyproject.toml` exists — no entry-point update needed

---

## Part 2: `trim_trailing_silence()`

### New function signature

```python
def trim_trailing_silence(mp3_path, silence_thresh=-50, min_silence_len=2000):
    """
    Returns: (True, seconds_removed) if trailing silence was trimmed,
             (False, 0.0) if criteria not met or error.
    Non-destructive: file is only overwritten if trim criteria are met.
    """
```

### Algorithm

```python
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from mutagen.mp3 import MP3 as MutagenMP3

audio = AudioSegment.from_mp3(mp3_path)

# Detect trailing silence by reversing: detect_leading_silence on reversed audio
# returns how many ms of silence are at the END of the original track.
trim_ms = detect_leading_silence(
    audio.reverse(),
    silence_threshold=silence_thresh,
    chunk_size=10,
)

if trim_ms < min_silence_len:
    return (False, 0.0)

# Read original bitrate (bits/sec → kbps via integer division)
try:
    bitrate = MutagenMP3(mp3_path).info.bitrate // 1000
except Exception:
    bitrate = 192  # safe fallback

trimmed = audio[:-trim_ms]
trimmed.export(mp3_path, format='mp3', bitrate=f'{bitrate}k')
return (True, trim_ms / 1000.0)
```

### Non-destructive guarantee

- File is **never written** unless `trim_ms >= min_silence_len`
- Exceptions inside the function are caught in `main()` — on error, original file is untouched

### New imports (top of soundklaut.py)

```python
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from mutagen.mp3 import MP3 as MutagenMP3
```

### requirements.txt addition

```
pydub>=0.25.1
```

---

## Integration in `main()`

### New CLI flags

```python
parser.add_argument('--no-trim', action='store_true',
                    help='Disable trailing silence trimming')
parser.add_argument('--silence-threshold', type=float, default=-50.0, metavar='DB',
                    help='Silence threshold in dBFS (default: -50)')
```

### Updated download loop (status == 'downloaded' branch)

```python
if status == 'downloaded':
    info_json = result.with_suffix('.info.json')

    # Trim trailing silence
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
```

### Updated epilog examples

```
%(prog)s https://soundcloud.com/artist/track
%(prog)s url1 url2 --output ~/Music
%(prog)s --playlist https://soundcloud.com/artist/sets/name
%(prog)s <url> --no-trim
%(prog)s <url> --silence-threshold -40
```

---

## Testing Strategy

### `trim_trailing_silence` tests (unit)

Real audio required — create synthetic AudioSegment with known silence:

```python
from pydub import AudioSegment
from pydub.generators import Sine

def make_mp3_with_silence(path, audio_ms=3000, silence_ms=3000):
    tone = Sine(440).to_audio_segment(duration=audio_ms)
    silence = AudioSegment.silent(duration=silence_ms)
    (tone + silence).export(path, format='mp3', bitrate='128k')
```

Test cases:
- Silence > 2s at end → `(True, ~silence_duration)`
- Silence < 2s at end → `(False, 0.0)`
- No silence → `(False, 0.0)`
- Silence only in middle → `(False, 0.0)`

### `main()` integration tests

Mock `trim_trailing_silence` at `soundklaut.trim_trailing_silence`. Test:
- `--no-trim` skips trim call
- trim result appended to console output
- trim exception doesn't crash main, original ✓ line still printed
