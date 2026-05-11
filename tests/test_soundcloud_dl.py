import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from soundcloud_dl import build_urls, download_track, set_metadata
