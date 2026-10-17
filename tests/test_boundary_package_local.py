"""Optional integration test against the operator's supplied Natural Earth files."""
import json
from pathlib import Path

import pytest

from earthglass.boundary_import import prepare


def test_us_state_package_preserves_global_borders(tmp_path):
    root = Path.home() / "Downloads" / "10m_cultural"
    if not root.exists():
        pytest.skip("Local Natural Earth source package not installed")
    base, enhanced = tmp_path / "base.json", tmp_path / "enhanced.json"
    prepare(root, base)
    result = prepare(root, enhanced, include_us_states=True)
    original = json.loads(base.read_text())
    combined = json.loads(enhanced.read_text())
    assert combined["features"][:len(original["features"])] == original["features"]
    states = [f for f in combined["features"] if f["properties"]["classification"] == "us_state"]
    assert len(states) == 51
    assert all(f["geometry"]["type"] in {"LineString", "MultiLineString"} for f in states)
    assert result["bytes"] < 16 * 1024 * 1024
