from __future__ import annotations

from weather_diag.areas.registry import load_area_registry


def test_area_registry_groups_station_records_by_town():
    registry = load_area_registry()

    town = registry.get_town("350203005")

    assert town.code == "350203005"
    assert town.name == "滨海街道"
    assert town.city_code == "350200"
    assert town.county_name == "思明区"
    assert town.station_count == 7
    assert town.points
    assert town.bbox[0] <= town.bbox[2]
    assert town.bbox[1] <= town.bbox[3]


def test_area_registry_lists_towns_for_city_or_county():
    registry = load_area_registry()

    city_towns = registry.towns_for_region("350200", region_level="city")
    county_towns = registry.towns_for_region("350203", region_level="county")

    assert len(city_towns) == 7
    assert [town.code for town in city_towns] == [town.code for town in county_towns]
    assert "350203005" in {town.code for town in city_towns}
