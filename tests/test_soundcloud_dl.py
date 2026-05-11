import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp
from mutagen.id3 import ID3

from soundcloud_dl import build_urls, set_metadata


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
