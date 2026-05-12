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
        status, result, _total_bytes = download_track(url, output_dir, archive_path, allow_playlist)

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


if __name__ == '__main__':
    main()
