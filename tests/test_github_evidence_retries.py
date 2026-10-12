"""A temporary read failure must not discard an otherwise complete briefing."""

import json
import subprocess
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from issueclaw import report_evidence as report


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, "gh", stderr="unexpected end of JSON input"),
        subprocess.CalledProcessError(1, "gh", stderr="HTTP 502: Bad Gateway"),
        subprocess.CalledProcessError(1, "gh", stderr="API rate limit exceeded"),
        subprocess.CalledProcessError(1, "gh", stderr="connection reset by peer"),
        subprocess.TimeoutExpired("gh", 180),
        subprocess.CompletedProcess("gh", 0, stdout='[{"number":'),
    ],
)
def test_transient_read_failure_recovers_complete_repository_evidence(
    tmp_path, failure
):
    empty = subprocess.CompletedProcess("gh", 0, stdout="[]")
    with (
        patch.object(subprocess, "run", side_effect=[failure, empty, empty]),
        patch.object(time, "sleep"),
    ):
        manifest = report.collect(
            {"repos": ["org/backend"]},
            datetime(2026, 10, 9, tzinfo=timezone.utc),
            datetime(2026, 10, 12, tzinfo=timezone.utc),
            tmp_path,
        )
    assert manifest["complete"]
    assert manifest["repositories"][0]["count"] == 0
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


@pytest.mark.parametrize("permanent", [False, True])
def test_failed_evidence_is_bounded_and_saved_as_incomplete(tmp_path, permanent):
    sleeps = []
    error = "HTTP 401: Bad credentials" if permanent else "unexpected end of JSON input"
    with (
        patch.object(
            subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "gh", stderr=error),
        ) as transport,
        patch.object(time, "sleep", side_effect=sleeps.append),
    ):
        manifest = report.collect(
            {"repos": ["org/backend"]},
            datetime(2026, 10, 9, tzinfo=timezone.utc),
            datetime(2026, 10, 12, tzinfo=timezone.utc),
            tmp_path,
        )
    assert not manifest["complete"]
    assert error in manifest["errors"][0]["error"]
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest
    # Bound actual network attempts, not just a configured retry count.
    assert transport.call_count == (1 if permanent else 4)
    assert len(sleeps) == (0 if permanent else 3)
    assert all(0 < delay <= 60 for delay in sleeps)


@pytest.mark.parametrize(
    "error",
    [
        "HTTP 403: Resource not accessible",
        "HTTP 404: Not Found",
        "unknown flag: --invalid",
    ],
)
def test_permanent_request_errors_fail_without_retry(error):
    with (
        patch.object(
            subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "gh", stderr=error),
        ) as transport,
        patch.object(time, "sleep") as sleep,
        pytest.raises(RuntimeError, match=error),
    ):
        report.gh_json("pr", "list", "-R", "org/backend")
    assert transport.call_count == 1
    sleep.assert_not_called()
