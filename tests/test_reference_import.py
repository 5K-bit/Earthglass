from earthglass.reference_import import label_feature


def test_country_uses_label_coordinates_instead_of_boundary_vertex():
    feature = label_feature({"NAME_EN": "Brazil", "LABEL_X": -53, "LABEL_Y": -10}, "countries")
    assert feature["geometry"]["coordinates"] == [-53, -10]
    assert feature["properties"]["name"] == "Brazil"


def test_city_uses_point_when_label_coordinates_absent():
    feature = label_feature({"NAME": "Seattle", "SCALERANK": 2}, "cities", [-122.3, 47.6])
    assert feature["geometry"]["coordinates"] == [-122.3, 47.6]


def test_invalid_coordinates_are_not_rendered_at_an_invented_location():
    assert label_feature({"NAME": "Unknown"}, "oceans") is None
    assert label_feature({"NAME": "Bad", "LABEL_X": float("nan"), "LABEL_Y": 0}, "oceans") is None
    assert label_feature({"NAME": "Bad", "LABEL_X": 0, "LABEL_Y": 91}, "cities") is None
