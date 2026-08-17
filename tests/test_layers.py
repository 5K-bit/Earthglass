import pytest

from earthglass.layers import LayerDefinition, LayerRegistry, registry


def test_default_registry_contains_earthquakes() -> None:
    layer = registry.get("earthquakes")
    assert layer.provider == "usgs"
    assert layer.geometry == "point"
    assert layer.refresh_interval == 300


def test_registry_rejects_duplicate_ids() -> None:
    local = LayerRegistry()
    layer = LayerDefinition(
        id="test",
        name="Test",
        description="Test layer",
        category="test",
        geometry="point",
        provider="fixture",
    )
    local.register(layer)
    with pytest.raises(ValueError):
        local.register(layer)


def test_registry_unknown_layer_is_explicit() -> None:
    local = LayerRegistry()
    with pytest.raises(KeyError, match="unknown layer"):
        local.get("missing")


def test_serialized_layer_has_no_renderer_dependency() -> None:
    payload = registry.get("earthquakes").as_dict()
    serialized = str(payload).lower()
    assert "leaflet" not in serialized
    assert "cesium" not in serialized
