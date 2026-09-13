import subprocess
import json
from datetime import datetime, timezone

import pytest

from issueclaw import report_evidence as report


START = datetime(2026, 9, 7, tzinfo=timezone.utc)
END = datetime(2026, 9, 11, 14, tzinfo=timezone.utc)


def pr(**overrides):
    return dict(
        number=1,
        title="ci: speed up tests AI-664",
        body="Related to BE-969",
        headRefName="fix",
        baseRefName="main",
        url="https://github.com/org/ai/pull/1",
        author={"login": "aviadr1"},
        state="MERGED",
        mergedAt="2026-09-10T10:00:00Z",
        updatedAt="2026-09-12T10:00:00Z",
        isDraft=False,
        **overrides,
    )


def test_linked_ci_work_survives_and_merge_query_recovers_later_updates(
    monkeypatch, tmp_path
):
    def fake(*args):
        if args[0] == "api":
            return [
                [
                    {
                        "body": "Verified success",
                        "created_at": "2026-09-10T12:00:00Z",
                        "html_url": "url",
                    }
                ],
                [],
            ]
        return [pr()] if args[args.index("--search") + 1].startswith("merged:") else []

    monkeypatch.setattr(report, "gh_json", fake)
    manifest = report.collect(
        {"repos": ["org/ai"], "people": {"aviadr1": "Aviad"}}, START, END, tmp_path
    )
    rows = report.json.loads((tmp_path / "org--ai.json").read_text())
    assert manifest["complete"]
    assert len(rows) == 1
    assert rows[0]["person"] == "Aviad"
    assert rows[0]["ticket_mentions"] == ["AI-664", "BE-969"]
    assert rows[0]["comments"][0]["body"] == "Verified success"


@pytest.mark.parametrize(
    "changes, expected",
    [
        (
            {"mergedAt": "2026-09-11T14:00:00Z", "updatedAt": "2026-09-11T14:00:00Z"},
            None,
        ),
        (
            {"mergedAt": None, "state": "OPEN", "updatedAt": "2026-09-10T10:00:00Z"},
            "open",
        ),
        (
            {
                "mergedAt": None,
                "state": "OPEN",
                "isDraft": True,
                "updatedAt": "2026-09-10T10:00:00Z",
            },
            "draft",
        ),
        (
            {"mergedAt": "2026-09-01T10:00:00Z", "updatedAt": "2026-09-10T10:00:00Z"},
            "follow_up",
        ),
    ],
)
def test_cutoff_and_activity_buckets(changes, expected):
    row = pr()
    row.update(changes)
    assert report.classify(row, START, END) == expected


@pytest.mark.parametrize("failure", ["access", "cap"])
def test_incomplete_sources_fail_explicitly(monkeypatch, tmp_path, failure):
    def fake(*args):
        if failure == "access":
            raise subprocess.CalledProcessError(1, "gh")
        return [pr()] * 1000

    monkeypatch.setattr(report, "gh_json", fake)
    manifest = report.collect({"repos": ["org/ai"]}, START, END, tmp_path)
    assert not manifest["complete"]
    assert manifest["errors"][0]["repo"] == "org/ai"
    assert (tmp_path / "manifest.json").exists()


@pytest.fixture
def github(monkeypatch):
    """Transport fixture: endpoint pages are data, not collector logic."""
    row = {
        **pr(),
        "mergedAt": None,
        "state": "OPEN",
        "createdAt": "2026-09-01T00:00:00Z",
    }
    responses = {"pr": [row], "issues": [[]], "reviews": [[]], "inline": [[]]}
    searches = []

    def request(*args):
        if args[0] == "pr":
            searches.append(args[args.index("--search") + 1])
            return responses["pr"]
        endpoint = args[-1]
        key = (
            "issues"
            if "/issues/" in endpoint
            else ("reviews" if "/reviews?" in endpoint else "inline")
        )
        response = responses[key]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(report, "gh_json", request)
    return responses, searches


def collected(tmp_path):
    manifest = report.collect({"repos": ["org/ai"]}, START, END, tmp_path)
    assert manifest["complete"], manifest
    return json.loads((tmp_path / "org--ai.json").read_text())


@pytest.mark.parametrize("channel", ["issues", "reviews", "inline"])
@pytest.mark.parametrize("latest", ["2026-09-11T14:05:00Z", "2026-09-15T00:00:00Z"])
@pytest.mark.parametrize(
    "timestamp, retained",
    [
        ("2026-09-06T23:59:59Z", False),
        ("2026-09-07T00:00:00Z", True),
        ("2026-09-11T13:59:59Z", True),
        ("2026-09-11T14:00:00Z", False),
    ],
)
def test_activity_window_is_independent_of_latest_metadata(
    github, tmp_path, channel, latest, timestamp, retained
):
    responses, searches = github
    responses["pr"][0]["updatedAt"] = latest
    key = "submitted_at" if channel == "reviews" else "created_at"
    responses[channel] = [[], [{key: timestamp, "body": "Verified outcome"}]]
    rows = collected(tmp_path)
    assert len(rows) == int(retained)
    assert any(query == "updated:>=2026-09-07" for query in searches)
    if retained:
        assert rows[0]["bucket"] == "activity"
        assert "Verified outcome" in json.dumps(rows)


@pytest.mark.parametrize("channel", ["issues", "inline"])
@pytest.mark.parametrize(
    "created, updated, body",
    [
        ("2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", "Verified outcome"),
        ("2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z", None),
    ],
)
def test_comment_edits_preserve_activity_without_backdating_text(
    github, tmp_path, channel, created, updated, body
):
    responses, _ = github
    responses[channel] = [
        [{"created_at": created, "updated_at": updated, "body": "Verified outcome"}]
    ]
    rows = collected(tmp_path)
    key = "comments" if channel == "issues" else "review_comments"
    comment = rows[0][key][0]
    assert comment["body"] == body
    assert comment["updated_at"] == updated
    assert comment["body_available_at_cutoff"] is (body is not None)


@pytest.mark.parametrize("channel", ["issues", "reviews", "inline"])
def test_event_endpoint_failure_never_claims_complete(github, tmp_path, channel):
    responses, _ = github
    responses[channel] = subprocess.CalledProcessError(1, "gh")
    manifest = report.collect({"repos": ["org/ai"]}, START, END, tmp_path)
    assert not manifest["complete"]
    assert manifest["errors"]
