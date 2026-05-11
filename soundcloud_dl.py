import argparse
import json
import sys
from pathlib import Path

import yt_dlp
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1
from rich.console import Console

console = Console()


def build_urls(args):
    urls = list(args.urls or [])
    if args.playlist:
        urls.append(args.playlist)
    if not urls:
        console.print("[red]Error: provide at least one URL or --playlist[/]")
        sys.exit(1)
    return urls


def download_track(url, output_dir):
    """Placeholder for Task 4."""
    pass


def set_metadata(mp3_path, info_json_path):
    """Set ID3 metadata from yt-dlp .info.json file."""
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
