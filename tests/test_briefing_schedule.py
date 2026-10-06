from datetime import datetime

import pytest

from issueclaw import briefing_schedule
from issueclaw import daily_briefing as daily


@pytest.mark.parametrize(
    ("event", "now", "enabled"),
    [
        ("schedule", "2026-10-06T05:00:00+00:00", False),
        ("schedule", "2026-10-07T05:00:00+00:00", True),
        ("workflow_dispatch", "2026-10-06T00:30:00+00:00", True),
        ("schedule", "2027-10-06T05:00:00+00:00", True),
    ],
)
def test_date_exclusion_only_skips_that_local_date_on_scheduled_runs(
    event, now, enabled
):
    config = {"timezone": "Asia/Jerusalem", "skip_scheduled_dates": ["2026-10-06"]}
    plan = briefing_schedule.plan(config, datetime.fromisoformat(now), event)
    assert plan == {"enabled": enabled, "cutoff": ""}


def test_early_manual_run_covers_only_work_available_now():
    now = datetime.fromisoformat("2026-10-06T00:30:00+00:00")
    config = {"timezone": "Asia/Jerusalem", "skip_scheduled_dates": ["2026-10-06"]}
    assert briefing_schedule.plan(config, now, "workflow_dispatch", early=True) == {
        "enabled": True,
        "cutoff": now.isoformat(),
    }
    with pytest.raises(ValueError, match="manual"):
        briefing_schedule.plan(config, now, "schedule", early=True)


def test_early_and_following_briefings_share_a_boundary_without_gaps_or_repeats():
    config = {"timezone": "Asia/Jerusalem", "hour": 8, "weekdays": [0, 1, 2, 3, 4]}
    monday = "2026-10-05T05:00:00+00:00"
    early = "2026-10-06T00:30:00+00:00"
    start, end = daily.coverage_window(
        config, datetime.fromisoformat(early), monday, cutoff=early
    )
    assert (start.isoformat(), end.isoformat()) == (monday, early)
    start, end = daily.coverage_window(
        config, datetime.fromisoformat("2026-10-07T05:05:00+00:00"), early
    )
    assert (start.isoformat(), end.isoformat()) == (
        early,
        "2026-10-07T05:00:00+00:00",
    )
