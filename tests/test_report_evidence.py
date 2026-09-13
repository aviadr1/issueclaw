import subprocess
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
