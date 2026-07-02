import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp
from mutagen.id3 import ID3
from pydub import AudioSegment
from pydub.generators import Sine

from soundklaut import build_urls, download_track, main, set_metadata, trim_trailing_silence


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

        def fake_download(urls):
            if raises:
                raise raises
            for payload in (hook_payloads or []):
                for hook in opts.get('progress_hooks', []):
                    hook(payload)
            return 0

        inner.download = fake_download
        cm.__enter__ = MagicMock(return_value=inner)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return factory


@patch('soundklaut.yt_dlp.YoutubeDL')
def test_download_track_downloaded(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    payload = {'status': 'finished', 'filename': str(tmp_path / 'Artist - Title.webm')}
    mock_ydl.side_effect = _make_ydl_mock(hook_payloads=[payload])

    status, path, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'downloaded'
    assert path == tmp_path / 'Artist - Title.mp3'


@patch('soundklaut.yt_dlp.YoutubeDL')
def test_download_track_skipped(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    mock_ydl.side_effect = _make_ydl_mock(hook_payloads=[])  # no hooks fired = skipped

    status, path, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'skipped'
    assert path is None


@patch('soundklaut.yt_dlp.YoutubeDL')
def test_download_track_error(mock_ydl, tmp_path):
    archive = tmp_path / 'downloaded.txt'
    mock_ydl.side_effect = _make_ydl_mock(
        raises=yt_dlp.utils.DownloadError('404 Not Found')
    )

    status, msg, total = download_track('https://soundcloud.com/a/t', tmp_path, archive)

    assert status == 'error'
    assert '404' in msg


@patch('soundklaut.yt_dlp.YoutubeDL')
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


@patch('soundklaut.yt_dlp.YoutubeDL')
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


@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_calls_set_metadata_on_download(mock_set_metadata, mock_download_track, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    info_json = mp3.with_suffix('.info.json')
    info_json.write_text('{}')

    mock_download_track.return_value = ('downloaded', mp3, None)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        main()

    mock_set_metadata.assert_called_once_with(mp3, mp3.with_suffix('.info.json'))


@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_skipped_does_not_call_set_metadata(mock_set_metadata, mock_download_track, tmp_path):
    mock_download_track.return_value = ('skipped', None, None)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        main()

    mock_set_metadata.assert_not_called()


@patch('soundklaut.download_track')
def test_main_all_failed_exits_one(mock_download_track, tmp_path):
    mock_download_track.return_value = ('error', 'HTTP 404', None)

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_partial_failure_exits_zero(mock_set_metadata, mock_download_track, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')

    mock_download_track.side_effect = [
        ('downloaded', mp3, None),
        ('error', 'HTTP 404', None),
    ]

    with patch('sys.argv', ['soundklaut.py',
                            'https://soundcloud.com/a/1',
                            'https://soundcloud.com/a/2',
                            '--output', str(tmp_path)]):
        main()  # must not raise — partial success = exit 0


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


@patch('soundklaut.trim_trailing_silence')
@patch('soundklaut.download_track')
@patch('soundklaut.set_metadata')
def test_main_trim_called_with_defaults(mock_set_metadata, mock_download_track, mock_trim, tmp_path):
    mp3 = tmp_path / 'Artist - Title.mp3'
    mp3.write_bytes(b'')
    mp3.with_suffix('.info.json').write_text('{}')
    mock_download_track.return_value = ('downloaded', mp3, None)
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
    mock_download_track.return_value = ('downloaded', mp3, None)

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
    mock_download_track.return_value = ('downloaded', mp3, None)
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
    mock_download_track.return_value = ('downloaded', mp3, None)
    mock_trim.side_effect = Exception('pydub decode error')

    with patch('sys.argv', ['soundklaut.py', 'https://soundcloud.com/a/t',
                            '--output', str(tmp_path)]):
        main()  # must not raise

    mock_set_metadata.assert_called_once()  # trim failed but download path continued
