import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from soundcloud_dl import build_urls


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
