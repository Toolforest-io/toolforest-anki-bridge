import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolforest_bridge import version  # noqa: E402


def test_addon_version_reads_manifest():
    version.addon_version.cache_clear()
    assert version.addon_version() == "0.1.3"
