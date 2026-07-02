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
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()


def _ffmpeg_exe() -> str:
    """Locate ffmpeg: PyInstaller bundle → imageio-ffmpeg → Homebrew → PATH."""
    import glob, os
    if getattr(sys, 'frozen', False):
        bundle = Path(sys._MEIPASS)
        # Exact name first (if we ever bundle a plain 'ffmpeg' binary)
        p = bundle / 'ffmpeg'
        if p.exists():
            return str(p)
        # imageio_ffmpeg bundles a versioned binary, e.g. ffmpeg-macos-aarch64-v7.1
        for pattern in (
            str(bundle / 'imageio_ffmpeg' / 'binaries' / 'ffmpeg*'),
            str(bundle / 'ffmpeg*'),
        ):
            matches = [m for m in glob.glob(pattern) if os.access(m, os.X_OK)]
            if matches:
                return matches[0]
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    for candidate in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg'):
        if Path(candidate).exists():
            return candidate
    return 'ffmpeg'


# Resolved once at import time; shared by pydub, yt-dlp, and spotdl calls.
_FFMPEG = _ffmpeg_exe()
AudioSegment.converter = _FFMPEG
AudioSegment.ffmpeg = _FFMPEG


def is_spotify_url(url: str) -> bool:
    return 'open.spotify.com' in url or url.startswith('spotify:')


def is_spotify_podcast_url(url: str) -> bool:
    return is_spotify_url(url) and any(
        k in url for k in ('/show/', '/episode/', 'spotify:show:', 'spotify:episode:')
    )


# ── Spotify Podcast Download ──────────────────────────────────────────────────

_BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)
_SPOTIFY_APP_VERSION = '1.2.52.442.g929a9b89'
_SPOTIFY_CLIENT_ID   = 'd8a5ed958d274c2e8ee717e6a4b0971d'  # Spotify Web Player


def _spotify_base62_to_hex(spotify_id: str) -> str:
    """Spotify-ID (22 Zeichen Base62) → 32-stellige Hex-GID (16 Byte)."""
    ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    n = 0
    for ch in spotify_id:
        n = n * 62 + ALPHABET.index(ch)
    return format(n, '032x')


def _get_spotify_tokens() -> 'tuple[str, str]':
    """
    Gibt (access_token, client_token) zurück.

    Spotify's get_access_token erfordert Session-Cookies (sp_t).
    Wir nutzen eine requests.Session: erst open.spotify.com besuchen
    (Cookies werden automatisch gesetzt), dann Token holen.
    """
    import requests as req
    import uuid

    headers = {
        'User-Agent': _BROWSER_UA,
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    session = req.Session()
    session.headers.update(headers)

    # Schritt 1: Hauptseite besuchen → sp_t und andere Cookies setzen lassen
    session.get('https://open.spotify.com/', timeout=15)

    # Schritt 2: Access Token mit den frisch gesetzten Cookies holen
    r = session.get(
        'https://open.spotify.com/get_access_token',
        params={'reason': 'transport', 'productType': 'web_player'},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    access_token = data.get('accessToken', '')
    if not access_token:
        raise RuntimeError(f'Kein accessToken in Antwort: {data}')

    # Schritt 3: Client Token für spclient API
    r2 = session.post(
        'https://clienttoken.spotify.com/v1/clienttoken',
        json={
            'client_data': {
                'client_version': _SPOTIFY_APP_VERSION,
                'client_id': _SPOTIFY_CLIENT_ID,
                'js_sdk_data': {
                    'device_brand': 'Apple',
                    'device_model': 'MacBook',
                    'os': 'macos',
                    'os_version': '10.15.7',
                    'device_id': str(uuid.uuid4()),
                    'device_type': 'computer',
                },
            }
        },
        timeout=15,
    )
    r2.raise_for_status()
    client_token = r2.json().get('granted_token', {}).get('token', '')

    return access_token, client_token


def _download_spotify_episode_direct(
    episode_id: str,
    ep_name: str,
    show_name: str,
    output_dir: Path,
    progress_callback=None,
) -> tuple:
    """
    Lädt die Spotify-Episode direkt vom CDN herunter und konvertiert zu MP3.

    Funktioniert ohne Premium und ohne Login — Podcast-Episoden haben kein DRM.

    Ablauf:
      1. Anonymes Token holen
      2. Base62-ID → Hex-GID
      3. spclient Metadaten → File-ID
      4. storage-resolve → CDN-URL
      5. OGG herunterladen → ffmpeg → MP3
    """
    import requests as req
    import subprocess

    try:
        if progress_callback:
            progress_callback(0, None, 'Hole Spotify-Token…')
        access_token, client_token = _get_spotify_tokens()
    except Exception as e:
        return ('error', f'Token-Fehler: {e}', None)

    spc_headers = {
        'Authorization':      f'Bearer {access_token}',
        'Client-Token':       client_token,
        'Spotify-App-Version': _SPOTIFY_APP_VERSION,
        'app-platform':       'WebPlayer',
        'User-Agent':         _BROWSER_UA,
        'Accept':             'application/json',
    }

    # Schritt 2: Metadaten (File-ID)
    try:
        if progress_callback:
            progress_callback(0, None, 'Hole Episoden-Metadaten von Spotify…')
        hex_gid = _spotify_base62_to_hex(episode_id)
        r = req.get(
            f'https://spclient.wg.spotify.com/metadata/4/episode/{hex_gid}?market=from_token',
            headers=spc_headers,
            timeout=15,
        )
        r.raise_for_status()
        meta = r.json()
    except Exception as e:
        return ('error', f'Metadaten-Fehler: {e}', None)

    audio_files = meta.get('audio', []) or meta.get('video', [])
    if not audio_files:
        return ('error', f'Keine Audio-Datei in Spotify-Metadaten gefunden: {meta}', None)

    # Höchste Qualität = letzter Eintrag
    file_id = audio_files[-1].get('file_id', '')
    if not file_id:
        return ('error', 'Leere File-ID in Spotify-Metadaten', None)

    # Schritt 3: CDN-URL
    try:
        if progress_callback:
            progress_callback(0, None, 'Hole CDN-URL…')
        r = req.get(
            f'https://spclient.wg.spotify.com/storage-resolve/files/audio/interactive/{file_id}'
            f'?alt=json&product=0',
            headers=spc_headers,
            timeout=15,
        )
        r.raise_for_status()
        cdn_urls = r.json().get('cdnurl', [])
        if not cdn_urls:
            return ('error', 'Keine CDN-URLs zurückgegeben', None)
        audio_url = cdn_urls[0]
    except Exception as e:
        return ('error', f'CDN-URL-Fehler: {e}', None)

    # Schritt 4: OGG herunterladen
    safe_show = _sanitize_filename(show_name or 'Spotify')
    safe_ep   = _sanitize_filename(ep_name  or episode_id)
    ogg_path  = output_dir / f'{safe_show} - {safe_ep}.ogg'
    mp3_path  = output_dir / f'{safe_show} - {safe_ep}.mp3'

    try:
        if progress_callback:
            progress_callback(0, None, f'Lade Audio: {safe_ep}…')
        with req.get(audio_url, stream=True, timeout=120,
                     headers={'User-Agent': _BROWSER_UA}) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length', 0)) or None
            done  = 0
            with open(ogg_path, 'wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress_callback:
                            progress_callback(done, total, str(ogg_path))
    except Exception as e:
        return ('error', f'Download-Fehler: {e}', None)

    # Schritt 5: OGG → MP3
    try:
        if progress_callback:
            progress_callback(0, None, 'Konvertiere OGG → MP3…')
        subprocess.run(
            [_FFMPEG, '-i', str(ogg_path), '-acodec', 'libmp3lame',
             '-ab', '320k', '-y', str(mp3_path)],
            check=True,
            capture_output=True,
        )
        ogg_path.unlink(missing_ok=True)
    except Exception as e:
        return ('error', f'ffmpeg-Fehler: {e}', None)

    return ('downloaded', mp3_path, total)


def _get_episode_meta(episode_id: str) -> dict:
    """
    Episodenname + Show-Name ermitteln — drei Strategien in Reihenfolge:

    1. Spotify-Episodenseite scrapen (og:title, kein Auth nötig)
    2. Anonymes Web-Player-Token + Spotify API
    3. Client-Credentials + Spotify API (spotdl-Keys)
    """
    import re
    import requests as req

    headers = {'User-Agent': _BROWSER_UA, 'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'}

    # ── Strategie 1: Seiten-Scraping ─────────────────────────────────────────
    try:
        r = req.get(
            f'https://open.spotify.com/episode/{episode_id}',
            headers=headers,
            timeout=15,
        )
        if r.ok:
            html = r.text

            # og:title = Episodenname (ohne Show-Name)
            ep_name = ''
            m_og = re.search(
                r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html
            )
            if m_og:
                ep_name = m_og.group(1).strip()

            # <title> = "Episodenname - Showname | Podcast on Spotify"
            show_name = ''
            m_title = re.search(r'<title>([^<]+)</title>', html)
            if m_title:
                page_title = m_title.group(1).strip()
                # Spotify-Suffix abschneiden
                for suffix in (' | Podcast on Spotify', ' on Spotify', ' | Spotify'):
                    if page_title.endswith(suffix):
                        page_title = page_title[: -len(suffix)].strip()
                # Show-Name = alles nach dem letzten " - " oder " | "
                if ep_name and ep_name in page_title:
                    remainder = page_title[len(ep_name):].strip()
                    show_name = re.sub(r'^[\s\-|]+', '', remainder).strip()
                elif ' - ' in page_title:
                    show_name = page_title.rsplit(' - ', 1)[-1].strip()
                elif ' | ' in page_title:
                    show_name = page_title.rsplit(' | ', 1)[-1].strip()

            if ep_name and show_name:
                return {'ep_name': ep_name, 'show_name': show_name}

            # Fallback: JSON-LD eingebettet
            m2 = re.search(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                           html, re.DOTALL | re.IGNORECASE)
            if m2:
                import json as _json
                try:
                    ld = _json.loads(m2.group(1))
                    ep_name = ld.get('name', '')
                    show_name = (ld.get('partOfSeries') or {}).get('name', '')
                    if ep_name and show_name:
                        return {'ep_name': ep_name, 'show_name': show_name}
                except Exception:
                    pass
    except Exception:
        pass

    # ── Strategie 2: Anonymes Web-Player-Token ────────────────────────────────
    try:
        r = req.get(
            'https://open.spotify.com/get_access_token',
            params={'reason': 'transport', 'productType': 'web_player'},
            headers=headers,
            timeout=15,
        )
        if r.ok:
            token = r.json().get('accessToken', '')
            if token:
                r2 = req.get(
                    f'https://api.spotify.com/v1/episodes/{episode_id}?market=DE',
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=15,
                )
                if r2.ok:
                    data = r2.json()
                    return {
                        'ep_name': data.get('name', ''),
                        'show_name': data.get('show', {}).get('name', ''),
                    }
    except Exception:
        pass

    # ── Strategie 3: Client-Credentials ──────────────────────────────────────
    try:
        import base64
        _cid = '5f573c9620494bae87890c0f08a60293'
        _cs  = '212476d9b0f3472eaa762d90b19b0ba8'
        creds = base64.b64encode(f'{_cid}:{_cs}'.encode()).decode()
        r = req.post(
            'https://accounts.spotify.com/api/token',
            headers={'Authorization': f'Basic {creds}'},
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
        if r.ok:
            token = r.json().get('access_token', '')
            if token:
                r2 = req.get(
                    f'https://api.spotify.com/v1/episodes/{episode_id}?market=DE',
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=15,
                )
                if r2.ok:
                    data = r2.json()
                    return {
                        'ep_name': data.get('name', ''),
                        'show_name': data.get('show', {}).get('name', ''),
                    }
    except Exception:
        pass

    return {}


def _find_rss_via_apple(show_name: str) -> 'str | None':
    """Apple-Podcasts-Suche → RSS-Feed-URL (kostenlos, keine API-Keys)."""
    if not show_name:
        return None
    try:
        import requests as req
        r = req.get(
            'https://itunes.apple.com/search',
            params={'term': show_name, 'entity': 'podcast', 'limit': 5},
            headers={'User-Agent': _BROWSER_UA},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get('results', [])
        if results:
            return results[0].get('feedUrl')
    except Exception:
        pass
    return None


def _find_episode_in_rss(rss_url: str, ep_title: str) -> 'str | None':
    """Episode-MP3-URL aus RSS-Feed heraussuchen (Titel-Matching)."""
    try:
        import requests as req
        import xml.etree.ElementTree as ET

        r = req.get(rss_url, headers={'User-Agent': _BROWSER_UA}, timeout=20)
        r.raise_for_status()

        # Strip namespace declarations that confuse ElementTree
        content = r.content.replace(b' xmlns="', b' xmlnsx="')
        root = ET.fromstring(content)

        ep_lower = ep_title.lower().strip() if ep_title else ''
        best_url: 'str | None' = None
        best_score = -1

        for item in root.iter('item'):
            title_el = item.find('title')
            item_title = (title_el.text or '').lower().strip() if title_el is not None else ''

            enclosure = item.find('enclosure')
            if enclosure is None:
                continue
            url = enclosure.get('url', '').split('?')[0]  # strip tracking params
            if not url:
                continue

            score = 0
            if ep_lower:
                if ep_lower == item_title:
                    score = 10
                elif ep_lower in item_title or item_title in ep_lower:
                    score = 5
                else:
                    words = [w for w in ep_lower.split() if len(w) > 3]
                    score = sum(1 for w in words if w in item_title)
            else:
                score = 0  # no title → take first

            if score > best_score or best_url is None:
                best_score = score
                best_url = url

        return best_url
    except Exception as e:
        console.print(f'  [yellow]⚠[/]  RSS-Parsing fehlgeschlagen: {e}')
        return None


def _sanitize_filename(s: str) -> str:
    """Ungültige Zeichen für Dateinamen entfernen."""
    return ''.join(c if c.isalnum() or c in ' -_.,()[]' else '_' for c in s).strip()


def _download_direct_url(
    mp3_url: str,
    ep_name: str,
    show_name: str,
    output_dir: Path,
    progress_callback=None,
) -> tuple:
    """Direkte MP3-URL streamen + mit Fortschrittsanzeige speichern."""
    try:
        import requests as req

        safe_show = _sanitize_filename(show_name)
        safe_ep = _sanitize_filename(ep_name)
        filename = output_dir / f'{safe_show} - {safe_ep}.mp3'

        if progress_callback:
            progress_callback(downloaded_bytes=0, total_bytes=None, filename=str(filename))

        with req.get(mp3_url, stream=True, timeout=120,
                     headers={'User-Agent': _BROWSER_UA}) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length', 0)) or None
            downloaded = 0
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(
                                downloaded_bytes=downloaded,
                                total_bytes=total,
                                filename=str(filename),
                            )

        return ('downloaded', filename, total)
    except Exception as e:
        return ('error', str(e), None)


def _download_spotify_podcast(url, output_dir, progress_callback=None) -> tuple:
    """
    Spotify-Podcast-Episode herunterladen via RSS.

    Ablauf:
      1. Episode-ID aus URL extrahieren
      2. Metadaten holen: erst Seiten-Scraping, dann API (3 Fallbacks)
      3. RSS-Feed via Apple Podcasts Search finden
      4. Episode-MP3-URL im RSS-Feed suchen
      5. MP3 direkt herunterladen (Podcast-Episoden haben kein DRM)
    """
    import re

    ep_match = re.search(r'/episode/([A-Za-z0-9]+)', url)
    show_match = re.search(r'/show/([A-Za-z0-9]+)', url)
    episode_id = ep_match.group(1) if ep_match else None
    show_id = show_match.group(1) if show_match else None

    if not episode_id and not show_id:
        return ('error', 'Ungültige Spotify-Podcast-URL', None)

    # Schritt 1: Metadaten (Titel, Show-Name)
    if progress_callback:
        progress_callback(downloaded_bytes=0, total_bytes=None, filename='Lade Metadaten von Spotify…')

    ep_name   = ''
    show_name = ''
    if episode_id:
        meta      = _get_episode_meta(episode_id)
        ep_name   = meta.get('ep_name', '')
        show_name = meta.get('show_name', '')

    # Schritt 2a: librespot (direktes Protokoll, kein Web-API — beste Option)
    if episode_id:
        result = _download_with_librespot(
            episode_id, ep_name, show_name, output_dir, progress_callback
        )
        if result[0] == 'downloaded':
            return result
        if result[1] != 'SPOTIFY_NO_CREDENTIALS':
            console.print(f'  [yellow]⚠[/]  librespot: {result[1]}')

    # Schritt 2b: Direkt via spclient-CDN (anonymes Token)
    if episode_id:
        result = _download_spotify_episode_direct(
            episode_id, ep_name, show_name, output_dir, progress_callback
        )
        if result[0] == 'downloaded':
            return result
        console.print(f'  [yellow]⚠[/]  CDN-Download fehlgeschlagen: {result[1]}')

    if not show_name:
        return (
            'error',
            'Spotify-Metadaten konnten nicht geladen werden.\n'
            'Prüfe die Internetverbindung oder ob der Podcast öffentlich ist.',
            None,
        )

    # Schritt 3: RSS-Feed (für echte Podcasts mit öffentlichem Feed)
    if progress_callback:
        progress_callback(downloaded_bytes=0, total_bytes=None,
                          filename=f'Suche RSS-Feed für „{show_name}"…')
    rss_url = _find_rss_via_apple(show_name)
    if rss_url:
        if progress_callback:
            progress_callback(downloaded_bytes=0, total_bytes=None,
                              filename='Suche Episode im RSS-Feed…')
        mp3_url = _find_episode_in_rss(rss_url, ep_name)
        if mp3_url:
            return _download_direct_url(mp3_url, ep_name, show_name, output_dir, progress_callback)

    return (
        'error',
        f'Download fehlgeschlagen. Podcast: „{show_name}" — Episode: „{ep_name}"',
        None,
    )


def build_urls(args):
    urls = list(args.urls or [])
    if args.playlist:
        urls.append(args.playlist)
    if not urls:
        console.print('[red]Error: provide at least one URL or --playlist[/]')
        sys.exit(1)
    return urls


def set_metadata(mp3_path, info_json_path):
    """Set ID3 text tags from yt-dlp .info.json and delete the json file."""
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

    # Snapshot ID3 tags (including embedded cover art) before pydub overwrites the file.
    try:
        saved_tags = ID3(mp3_path)
    except Exception:
        saved_tags = None

    try:
        bitrate = MutagenMP3(mp3_path).info.bitrate // 1000
    except Exception:
        bitrate = 192

    trimmed = audio[:-trim_ms]
    trimmed.export(mp3_path, format='mp3', bitrate=f'{bitrate}k')

    # Restore all ID3 tags (cover art, title, artist, …) that pydub stripped.
    if saved_tags:
        saved_tags.save(mp3_path)

    return (True, trim_ms / 1000.0)


# ── librespot (direkter Spotify-Download, kein Web-API nötig) ────────────────

_CREDENTIALS_FILE = Path.home() / '.soundklaut_spotify.json'


def spotify_credentials_saved() -> bool:
    return _CREDENTIALS_FILE.exists()


def save_spotify_credentials(email: str, password: str):
    import json
    _CREDENTIALS_FILE.write_text(json.dumps({'email': email, 'password': password}))
    _CREDENTIALS_FILE.chmod(0o600)


def load_spotify_credentials() -> 'tuple[str,str] | None':
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        import json
        d = json.loads(_CREDENTIALS_FILE.read_text())
        return d.get('email', ''), d.get('password', '')
    except Exception:
        return None


def _download_with_librespot(
    episode_id: str,
    ep_name: str,
    show_name: str,
    output_dir: Path,
    progress_callback=None,
) -> tuple:
    """
    Lädt Spotify-Episode direkt via librespot-Protokoll (identisch zur Spotify-App).
    Benötigt: gespeicherte Spotify-Zugangsdaten (einmalige Einrichtung).
    Umgeht Web-API und Akamai-WAF komplett.
    """
    import subprocess

    try:
        from librespot.core import Session
        from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
        from librespot.metadata import EpisodeId
    except ImportError:
        return ('error', 'librespot nicht installiert', None)

    creds = load_spotify_credentials()
    if not creds:
        return ('error', 'SPOTIFY_NO_CREDENTIALS', None)   # Signal für GUI
    email, password = creds

    # ── Session aufbauen ──
    try:
        if progress_callback:
            progress_callback(0, None, 'Verbinde mit Spotify…')
        conf = Session.Configuration.Builder().set_store_credentials(False).build()
        session = Session.Builder(conf).user_pass(email, password).create()
    except Exception as e:
        return ('error', f'Spotify-Login fehlgeschlagen: {e}', None)

    # ── Episode-Stream laden ──
    try:
        if progress_callback:
            progress_callback(0, None, 'Lade Episode-Stream…')
        ep_id = EpisodeId.from_base62(episode_id)
        stream = session.content_feeder().load_episode(
            ep_id,
            VorbisOnlyAudioQuality(AudioQuality.HIGH),
            False,
            None,
        )
    except Exception as e:
        return ('error', f'Stream-Fehler: {e}', None)

    # ── OGG herunterladen ──
    safe_show = _sanitize_filename(show_name or 'Spotify')
    safe_ep   = _sanitize_filename(ep_name   or episode_id)
    ogg_path  = output_dir / f'{safe_show} - {safe_ep}.ogg'
    mp3_path  = output_dir / f'{safe_show} - {safe_ep}.mp3'

    try:
        if progress_callback:
            progress_callback(0, None, f'Lade Audio: {safe_ep}…')
        input_stream = stream.input_stream.stream()
        total = getattr(stream.input_stream, 'size', None)
        done  = 0
        with open(ogg_path, 'wb') as f:
            while True:
                chunk = input_stream.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total, str(ogg_path))
    except Exception as e:
        ogg_path.unlink(missing_ok=True)
        return ('error', f'Download-Fehler: {e}', None)

    # ── OGG → MP3 ──
    try:
        if progress_callback:
            progress_callback(0, None, 'Konvertiere OGG → MP3…')
        subprocess.run(
            [_FFMPEG, '-i', str(ogg_path), '-acodec', 'libmp3lame',
             '-ab', '320k', '-y', str(mp3_path)],
            check=True, capture_output=True,
        )
        ogg_path.unlink(missing_ok=True)
    except Exception as e:
        return ('error', f'ffmpeg-Fehler: {e}', None)

    return ('downloaded', mp3_path, total)


# ── Audio-Capture (TuneFab-Methode) ──────────────────────────────────────────

def find_blackhole_device() -> 'int | None':
    """Gibt den sounddevice-Index des BlackHole-Eingangs zurück, oder None."""
    try:
        import sounddevice as sd
        for i, dev in enumerate(sd.query_devices()):
            if 'BlackHole' in dev['name'] and dev['max_input_channels'] > 0:
                return i
    except Exception:
        pass
    return None


def record_from_audio_capture(
    output_dir: Path,
    filename_stem: str,
    stop_event,            # threading.Event — wird von aussen gesetzt zum Stoppen
    progress_callback=None,
    silence_stop_secs: float = 8.0,
    samplerate: int = 44100,
) -> tuple:
    """
    Nimmt Audio vom BlackHole-Eingang auf (macOS).

    Ablauf für den User:
      1. BlackHole installieren: https://existential.audio/blackhole/
      2. Systemeinstellungen → Ton → Ausgabe → BlackHole 2ch wählen
      3. Episode in Spotify starten
      4. In soundklaut auf "Aufnahme stoppen" klicken (oder automatischer Stopp bei Stille)

    Gibt ('downloaded', mp3_path, None) oder ('error', msg, None) zurück.
    """
    import subprocess
    import threading

    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        return (
            'error',
            'sounddevice / numpy fehlt. Bitte: pip install sounddevice numpy',
            None,
        )

    bh_idx = find_blackhole_device()
    if bh_idx is None:
        return (
            'error',
            (
                'BlackHole nicht gefunden.\n'
                'Installiere BlackHole 2ch (kostenlos):\n'
                'https://existential.audio/blackhole/\n\n'
                'Danach:\n'
                '  Systemeinstellungen → Ton → Ausgabe → BlackHole 2ch'
            ),
            None,
        )

    mp3_path = output_dir / f'{filename_stem}.mp3'
    wav_path  = output_dir / f'{filename_stem}.wav'

    chunks: list = []
    silence_secs = [0.0]
    local_stop = threading.Event()

    def _callback(indata, frames, _time, _status):
        chunks.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata ** 2)))
        if rms < 0.0005:
            silence_secs[0] += frames / samplerate
            if silence_secs[0] >= silence_stop_secs:
                local_stop.set()
        else:
            silence_secs[0] = 0.0
        if progress_callback:
            total_secs = len(chunks) * frames / samplerate
            progress_callback(
                downloaded_bytes=int(total_secs),
                total_bytes=None,
                filename=f'Aufnahme läuft … {int(total_secs // 60):02d}:{int(total_secs % 60):02d}',
            )

    if progress_callback:
        progress_callback(0, None, 'Aufnahme gestartet — spiele Episode in Spotify ab …')

    try:
        with sd.InputStream(
            device=bh_idx,
            channels=2,
            samplerate=samplerate,
            dtype='float32',
            callback=_callback,
        ):
            while not stop_event.is_set() and not local_stop.is_set():
                import time; time.sleep(0.2)
    except Exception as e:
        return ('error', f'Aufnahme-Fehler: {e}', None)

    if not chunks:
        return ('error', 'Keine Audiodaten aufgenommen.', None)

    # WAV speichern
    try:
        import numpy as np
        audio = np.concatenate(chunks, axis=0)
        import wave, struct
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
    except Exception as e:
        return ('error', f'WAV-Fehler: {e}', None)

    # WAV → MP3
    if progress_callback:
        progress_callback(0, None, 'Konvertiere zu MP3 …')
    try:
        subprocess.run(
            [_FFMPEG, '-i', str(wav_path), '-acodec', 'libmp3lame',
             '-ab', '320k', '-y', str(mp3_path)],
            check=True, capture_output=True,
        )
        wav_path.unlink(missing_ok=True)
    except Exception as e:
        return ('error', f'ffmpeg-Fehler: {e}', None)

    return ('downloaded', mp3_path, None)


def download_track(url, output_dir, allow_playlist=False, progress_callback=None):
    """Download audio from SoundCloud, Spotify, or any yt-dlp-supported URL."""
    if is_spotify_podcast_url(url):
        return _download_spotify_podcast(url, output_dir, progress_callback)
    if is_spotify_url(url):
        return _download_spotify_music(url, output_dir, progress_callback)
    return _download_via_ytdlp(url, output_dir, allow_playlist, progress_callback)


def _download_via_ytdlp(url, output_dir, allow_playlist=False, progress_callback=None):
    """Download via yt-dlp (SoundCloud, Spotify podcasts, YouTube, …)."""
    downloaded_filename = []
    total_bytes_seen = [None]

    def progress_hook(d):
        if d['status'] == 'downloading' and progress_callback:
            try:
                downloaded = int(d.get('downloaded_bytes') or 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                total_bytes_seen[0] = total
                progress_callback(
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    filename=d.get('filename', ''),
                )
            except (TypeError, ValueError):
                pass
        if d['status'] == 'finished':
            downloaded_filename.append(d['filename'])

    opts = {
        'format': 'bestaudio/best',
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            },
            {
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False,
            },
        ],
        'outtmpl': str(output_dir / '%(uploader)s - %(title)s.%(ext)s'),
        'writethumbnail': True,
        'noplaylist': not allow_playlist,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        'ffmpeg_location': _FFMPEG,
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


def _download_spotify_music(url, output_dir, progress_callback=None):
    """Download Spotify music via spotdl (YouTube Music backend, no DRM issues)."""
    try:
        from spotdl import Spotdl
    except ImportError:
        return (
            'error',
            'spotdl fehlt — installiere es mit: pip install spotdl',
            None,
        )

    # Show indeterminate progress while spotdl works (no granular hooks available).
    if progress_callback:
        progress_callback(downloaded_bytes=0, total_bytes=None, filename='Spotify…')

    output_template = str(output_dir) + '/{artists} - {title}.{output-ext}'

    try:
        app = Spotdl(
            client_id='5f573c9620494bae87890c0f08a60293',
            client_secret='212476d9b0f3472eaa762d90b19b0ba8',
            downloader_settings={
                'output': output_template,
                'format': 'mp3',
                'bitrate': 'auto',
                'threads': 1,
                'ffmpeg': _FFMPEG,
                'overwrite': 'skip',
            },
        )
    except Exception as e:
        return ('error', f'spotdl-Init fehlgeschlagen: {e}', None)

    try:
        songs = app.search([url])
    except Exception as e:
        return ('error', f'Spotify-Suche fehlgeschlagen: {e}', None)

    if not songs:
        return ('skipped', None, None)

    downloaded_paths = []
    for song in songs:
        try:
            _, path = app.download(song)
            if path:
                downloaded_paths.append(Path(path))
        except Exception:
            pass

    if not downloaded_paths:
        return ('skipped', None, None)

    return ('downloaded', downloaded_paths[0], None)


def _short_url(url):
    parts = url.rstrip('/').split('/')
    return '/'.join(parts[-2:]) if len(parts) >= 2 else url


def _format_bytes(n):
    if n is None:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def main():
    parser = argparse.ArgumentParser(
        description='Download SoundCloud / Spotify tracks as MP3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  %(prog)s https://soundcloud.com/artist/track\n'
            '  %(prog)s https://open.spotify.com/track/...\n'
            '  %(prog)s https://open.spotify.com/show/...   (Podcast)\n'
            '  %(prog)s https://open.spotify.com/episode/... (Episode)\n'
            '  %(prog)s url1 url2 --output ~/Music\n'
            '  %(prog)s --playlist https://soundcloud.com/artist/sets/name\n'
            '  %(prog)s --playlist https://open.spotify.com/album/...\n'
            '  %(prog)s <url> --no-trim\n'
            '  %(prog)s <url> --silence-threshold -40'
        ),
    )
    parser.add_argument('urls', nargs='*', metavar='URL', help='Track / podcast URL(s)')
    parser.add_argument('--playlist', metavar='URL', help='Playlist, album, or show URL')
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
            TextColumn('{task.description}'),
            BarColumn(),
            TaskProgressColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            transient=True,
            console=console,
        ) as progress:
            task = progress.add_task(
                f'  [{i + 1}/{n}]  {track_name}', total=None
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
                            description=f'  [{_idx + 1}/{n}]  {track_name}',
                        )
                _progress.update(_task, completed=downloaded_bytes, total=total_bytes)
                file_size = total_bytes

            status, result, total = download_track(
                url, output_dir, allow_playlist,
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
                    console.print(f'  [yellow]⚠[/]  trim failed: {e}')

            info_json = result.with_suffix('.info.json')
            if info_json.exists():
                try:
                    set_metadata(result, info_json)
                except Exception as e:
                    console.print(
                        f'  [yellow]⚠[/]  {result.stem}  [dim](metadata failed: {e})[/]'
                    )

            size_str = (
                f'  [dim]{_format_bytes(total or file_size)}[/]'
                if (total or file_size) else ''
            )
            console.print(f'  [green]✓[/]  {track_name}{trim_note}{size_str}')
            downloaded += 1

        elif status == 'skipped':
            console.print(
                f'  [yellow]⏭[/]  {track_name}  [dim]already downloaded[/]'
            )
            skipped += 1

        else:
            console.print(f'  [red]✗[/]  {track_name}  [dim]{result}[/]')
            failed += 1

    console.print()
    console.rule(style='dim')
    console.print(
        f'  [bold]{downloaded}[/] downloaded · '
        f'[bold]{skipped}[/] skipped · '
        f'[bold]{failed}[/] failed\n'
    )

    if downloaded == 0 and failed > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
