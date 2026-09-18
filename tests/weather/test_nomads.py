from datetime import datetime, timezone

from earthglass.weather.gfs.layers import get_layer_spec
from earthglass.weather.gfs.nomads import build_gfs_layer_url, build_gfs_layer_urls, build_gfs_temperature_url


def test_builds_nomads_filter_url_for_temperature_analysis() -> None:
    url = build_gfs_temperature_url(datetime(2026, 8, 13, 12, tzinfo=timezone.utc))

    assert "filter_gfs_0p25.pl" in url
    assert "file=gfs.t12z.pgrb2.0p25.f000" in url
    assert "var_TMP=on" in url
    assert "lev_2_m_above_ground=on" in url
    assert "dir=%2Fgfs.20260813%2F12%2Fatmos" in url


def test_builds_nomads_filter_url_for_wind_components() -> None:
    url = build_gfs_layer_url(datetime(2026, 8, 13, 12, tzinfo=timezone.utc), get_layer_spec("wind10m"))

    assert "var_UGRD=on" in url
    assert "var_VGRD=on" in url
    assert "lev_10_m_above_ground=on" in url


def test_builds_cloud_cover_level_variants() -> None:
    urls = build_gfs_layer_urls(datetime(2026, 8, 13, 12, tzinfo=timezone.utc), get_layer_spec("cloudCover"))

    assert len(urls) == 3
    assert any("lev_entire_atmosphere=on" in url for url in urls)
    assert any("lev_entire_atmosphere_%5C%28considered_as_a_single_layer%5C%29=on" in url for url in urls)
    assert any("lev_entire_atmosphere_%28considered_as_a_single_layer%29=on" in url for url in urls)
