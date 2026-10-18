"""The Ride tab used to show no actual ride data at all — just a weather
forecast and fitness sparklines. _recent_rides_from_session backs the
"Recent rides" list that /progression now also returns.
"""

import pytest

import backend.main as m


def _activity(activity_id, start, type_key, **extra):
    return {
        "activityId": activity_id,
        "startTimeLocal": start,
        "duration": 3600,
        "activityType": {"typeKey": type_key},
        **extra,
    }


@pytest.mark.parametrize(
    "type_key",
    [
        "cycling",
        "road_biking",
        "mountain_biking",
        "gravel_cycling",
        "indoor_cycling",
        "virtual_ride",
        "cyclocross",
        "e_bike_fitness",
        "e_bike_mountain",
        "track_cycling",
        "bmx",
    ],
)
def test_recognises_all_known_garmin_cycling_type_keys(type_key):
    assert m._is_cycling_activity({"activityType": {"typeKey": type_key}})


@pytest.mark.parametrize("type_key", ["running", "swimming", "strength_training", "hiking"])
def test_rejects_non_cycling_type_keys(type_key):
    assert not m._is_cycling_activity({"activityType": {"typeKey": type_key}})


def test_filters_to_cycling_only():
    g = type(
        "FakeClient",
        (),
        {
            "get_activities": staticmethod(
                lambda start, limit: [
                    _activity(1, "2026-10-01 08:00:00", "cycling", distance=20000),
                    _activity(2, "2026-10-02 08:00:00", "running", distance=5000),
                    _activity(3, "2026-10-03 08:00:00", "road_biking", distance=30000),
                ]
            )
        },
    )()

    rides = m._recent_rides_from_session(g, limit=5)

    assert [r["activity_id"] for r in rides] == [3, 1]


def test_respects_limit_and_maps_fields():
    g = type(
        "FakeClient",
        (),
        {
            "get_activities": staticmethod(
                lambda start, limit: [
                    _activity(
                        1,
                        "2026-10-01 08:00:00",
                        "cycling",
                        activityName="Morning ride",
                        distance=20000,
                        avgPower=180,
                        averageHR=140,
                        elevationGain=250,
                        calories=600,
                    ),
                    _activity(2, "2026-10-02 08:00:00", "cycling", distance=10000),
                    _activity(3, "2026-10-03 08:00:00", "cycling", distance=15000),
                ]
            )
        },
    )()

    rides = m._recent_rides_from_session(g, limit=2)

    assert len(rides) == 2
    top = rides[0]
    assert top["activity_id"] == 3
    second = rides[1]
    assert second["activity_id"] == 2
    full = next(r for r in m._recent_rides_from_session(g, limit=5) if r["activity_id"] == 1)
    assert full["name"] == "Morning ride"
    assert full["distance_km"] == 20.0
    assert full["avg_power_w"] == 180
    assert full["avg_hr_bpm"] == 140
    assert full["elevation_gain_m"] == 250
    assert full["calories"] == 600
