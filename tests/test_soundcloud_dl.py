import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp
from mutagen.id3 import ID3

from soundcloud_dl import build_urls, download_track, set_metadata


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
