# SoundCloud Downloader — Design Spec
_Date: 2026-05-11_

## Overview

Single-file Python CLI (`soundcloud_dl.py`) that downloads SoundCloud tracks/playlists as MP3 files with ID3 metadata. Designed as a feeder for Spotify Local Files.

## Architecture

Single-file script. No classes. Functions are small and do one thing.

```
CLI-Args (argparse)
  ↓
build_urls(args) → list of URLs
  ↓
For each URL:
  download_track(url, output_dir, archive_path)
    → yt-dlp: --download-archive, --write-info-json, --no-playlist (default)
    → produces: Artist - Title.mp3 + Artist - Title.info.json
  set_metadata(mp3_path, info_json_path)
    → mutagen sets ID3 tags (title, artist, album, year)
    → deletes .info.json (cleanup)
  ↓
Rich progress: ✓ Downloaded / ⏭ Skipped / ✗ Failed
  ↓
Final summary (X downloaded, Y skipped, Z failed)
```

## Functions

| Function | Responsibility |
|---|---|
| `build_urls(args)` | Normalise argparse input to a flat list of URLs |
| `download_track(url, output_dir, archive_path)` | Run yt-dlp with all flags; return status + output path |
| `set_metadata(mp3_path, info_json_path)` | Read .info.json, write ID3 tags via mutagen, delete .info.json |
| `main()` | argparse + Rich progress loop |

## yt-dlp Configuration

```
-x --audio-format mp3 --audio-quality 0   # best MP3 quality
--download-archive downloads/downloaded.txt  # skip already-downloaded tracks
--write-info-json                            # metadata source
--no-playlist                                # default; overridden by --playlist flag
-o "%(uploader)s - %(title)s.%(ext)s"       # filename schema
```

## Duplicate Handling

yt-dlp manages duplicates via `--download-archive downloads/downloaded.txt`. No manual pre-check needed. Skipped tracks are reported in the summary.

## Metadata (ID3 Tags)

Source: `.info.json` written by yt-dlp post-download.
Fields set via mutagen: `TIT2` (title), `TPE1` (artist), `TALB` (album/uploader), `TDRC` (year).
`.info.json` is deleted after tags are written.

## File Structure

```
soundcloud-dl/
├── soundcloud_dl.py
├── requirements.txt
└── downloads/
    ├── downloaded.txt      # yt-dlp archive (auto-created)
    └── Artist - Title.mp3
```

## CLI Usage

```bash
python soundcloud_dl.py <url>
python soundcloud_dl.py <url1> <url2> <url3>
python soundcloud_dl.py --playlist <playlist-url>
python soundcloud_dl.py <url> --output ~/Music
```

## Error Handling

Each track is wrapped in try/except. A failed track logs `[red]FAILED: <reason>[/]` and processing continues. Exit code 0 if at least one track succeeded, 1 if all failed.

## Dependencies

```
yt-dlp
mutagen
rich
```

FFmpeg must be installed separately (required by yt-dlp for audio conversion).
