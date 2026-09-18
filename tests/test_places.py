from earthglass.spatial.places import cities, search_places


def test_packaged_world_city_index_and_accent_matching():
    assert len(cities()) > 30000
    assert search_places("São Paulo")[0]["label"].startswith("São Paulo")
    assert search_places("Sao Paulo")[0]["label"].startswith("São Paulo")
    assert search_places("Tokyo")[0]["longitude"] > 130
    assert search_places("New York")[0]["latitude"] > 40
    assert len(search_places("San", 5)) == 5
    assert not search_places("zzzz-no-city-matches")
