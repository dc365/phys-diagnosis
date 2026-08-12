from backend.app.main import layer_grid, layer_image_title


def test_layer_image_title_uses_ascii_variable_when_config_title_is_chinese():
    title = layer_image_title(
        "risk_short_duration_heavy_rain_score",
        {"title": "短时强降水风险评分", "variable": "risk_short_duration_heavy_rain_score"},
    )

    assert title == "risk_short_duration_heavy_rain_score"


def test_layer_image_title_keeps_ascii_title():
    title = layer_image_title(
        "omega700",
        {"title": "700hPa omega", "variable": "omega700"},
    )

    assert title == "700hPa omega"


def test_layer_grid_endpoint_returns_geojson_cells():
    body = layer_grid("risk_short_duration_heavy_rain_score", "ecmwf_demo", 24)
    assert body["type"] == "FeatureCollection"
    assert body["properties"]["title"] == "短时强降水风险评分"
    assert body["properties"]["count"] > 0
    assert body["features"][0]["geometry"]["type"] == "Polygon"
    assert "value" in body["features"][0]["properties"]
