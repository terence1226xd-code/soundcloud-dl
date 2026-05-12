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
                try:
                    set_metadata(result, info_json)
                except Exception as e:
                    console.print(f"  [yellow]⚠[/] {result.stem}  [dim](metadata failed: {e})[/]")
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
