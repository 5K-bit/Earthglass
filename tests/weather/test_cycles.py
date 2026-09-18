from datetime import datetime, timezone

from earthglass.weather.gfs.cycles import candidate_cycles, cycle_id, nominal_cycle


def test_nominal_cycle_rounds_down_to_gfs_schedule() -> None:
    moment = datetime(2026, 8, 13, 14, 37, tzinfo=timezone.utc)

    assert nominal_cycle(moment) == datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


def test_candidate_cycles_try_four_backwards_six_hours_apart() -> None:
    moment = datetime(2026, 8, 13, 1, 5, tzinfo=timezone.utc)

    assert candidate_cycles(moment) == [
        datetime(2026, 8, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 12, 18, tzinfo=timezone.utc),
        datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
        datetime(2026, 8, 12, 6, tzinfo=timezone.utc),
    ]


def test_cycle_id_is_stable() -> None:
    assert cycle_id(datetime(2026, 8, 13, 12, tzinfo=timezone.utc)) == "20260813_12"
