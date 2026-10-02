from datetime import datetime, timedelta, timezone

import pytest

from issueclaw import daily_briefing as daily
from issueclaw import report_evidence as report


@pytest.mark.parametrize(
    "date, hours",
    [
        ("2026-10-02T09:00:00+03:00", 24),
        ("2026-10-25T09:00:00+02:00", 25),
        ("2026-03-27T09:00:00+03:00", 23),
    ],
)
def test_local_day_has_no_gap_across_clock_changes(date, hours):
    start, end = daily.window(datetime.fromisoformat(date), "Asia/Jerusalem", 8)
    assert (end - start).total_seconds() == hours * 3600
    assert end.astimezone(daily.ZoneInfo("Asia/Jerusalem")).hour == 8
    next_start, _ = daily.window(end + timedelta(days=1, hours=3), "Asia/Jerusalem", 8)
    assert next_start == end


def test_scheduled_delay_preserves_eight_am_cutoff():
    start, end = daily.window(
        datetime(2026, 10, 2, 6, 45, tzinfo=timezone.utc), "Asia/Jerusalem", 8
    )
    assert end.isoformat() == "2026-10-02T05:00:00+00:00"
    assert start.isoformat() == "2026-10-01T05:00:00+00:00"


def test_collect_includes_old_open_drafts_and_reviewer_identity(monkeypatch, tmp_path):
    row = dict(
        number=1,
        title="Carry over BE-1",
        body="",
        headRefName="fix",
        baseRefName="main",
        url="https://github.com/org/repo/pull/1",
        author={"login": "author"},
        state="OPEN",
        mergedAt=None,
        updatedAt="2026-01-01T00:00:00Z",
        createdAt="2026-01-01T00:00:00Z",
        isDraft=True,
        reviewRequests=[{"login": "reviewer"}],
        reviewDecision="REVIEW_REQUIRED",
        headRefOid="abc",
        statusCheckRollup=[],
    )

    def github(*args):
        if args[:2] == ("pr", "view"):
            return {"headRefOid": "abc", "statusCheckRollup": []}
        if args[0] == "pr":
            return [row] if args[args.index("--state") + 1] == "open" else []
        return [[]]

    monkeypatch.setattr(report, "gh_json", github)
    start, end = daily.window(
        datetime(2026, 10, 2, 6, tzinfo=timezone.utc), "Asia/Jerusalem", 8
    )
    manifest = report.collect(
        {"repos": ["org/repo"], "people": {"reviewer": "Rae"}},
        start,
        end,
        tmp_path,
        include_open=True,
    )
    assert manifest["complete"]
    import json

    rows = json.loads((tmp_path / "org--repo.json").read_text())
    assert rows[0]["bucket"] == "draft"
    assert rows[0]["requested_reviewers"] == ["Rae"]


def test_publish_resumes_thread_without_reposting_completed_messages():
    state = {"messages": {}, "last_cutoff": None}
    saved = []

    class Slack:
        def __init__(self):
            self.sent = []

        def find(self, key):
            return None

        def post(self, text, key, thread):
            self.sent.append((text, key, thread))
            if text == "reply" and len(self.sent) == 2:
                raise daily.SlackRejected("outage")
            return str(len(self.sent))

    slack = Slack()
    messages = [("01.md", "top"), ("02.md", "reply")]
    with pytest.raises(RuntimeError):
        daily.publish(messages, state, "cutoff", slack, lambda s: saved.append(dict(s)))
    assert state["last_cutoff"] is None
    assert state["messages"]["cutoff/01.md"]["ts"] == "1"
    daily.publish(messages, state, "cutoff", slack, lambda s: saved.append(dict(s)))
    assert [x[0] for x in slack.sent] == ["top", "reply", "reply"]
    assert slack.sent[-1][2] == "1"
    assert state["last_cutoff"] == "cutoff"


def test_publish_recovers_acceptance_before_checkpoint():
    state = {"messages": {"cutoff/01.md": {"intent": True}}}

    class Slack:
        def find(self, key):
            return {"ts": "123", "text": "previous"}

        def post(self, *args):
            pytest.fail("must recover existing Slack message")

    daily.publish(
        [("01.md", "new generation")], state, "cutoff", Slack(), lambda s: None
    )
    assert state["last_cutoff"] == "cutoff"
    assert state["messages"]["cutoff/01.md"]["ts"] == "123"


def test_uncertain_reply_is_never_blindly_reposted():
    state = {
        "messages": {"cutoff/01.md": {"ts": "1"}, "cutoff/02.md": {"intent": True}}
    }

    class Slack:
        def find(self, key):
            return None

        def post(self, *args):
            pytest.fail("must not duplicate an uncertain message")

    with pytest.raises(RuntimeError, match="Uncertain Slack delivery"):
        daily.publish(
            [("01.md", "top"), ("02.md", "reply")],
            state,
            "cutoff",
            Slack(),
            lambda s: None,
        )
    assert state.get("last_cutoff") is None


def test_prepare_audits_daily_merges_carryover_and_changed_done_tickets(
    monkeypatch, tmp_path
):
    import json
    import subprocess

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    subprocess.run(["git", "init", str(mirror)], check=True, capture_output=True)
    ticket = mirror / "linear/teams/BE/issues/BE-1-example.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(
        "---\nidentifier: BE-1\ntitle: Completed work\nstatus: Done\nassignee: Rae\nurl: https://linear.app/example/BE-1\n---\nA concrete fix.\n"
    )
    subprocess.run(["git", "add", "."], cwd=mirror, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "ticket",
        ],
        cwd=mirror,
        check=True,
        capture_output=True,
        env=dict(
            daily.os.environ,
            GIT_AUTHOR_DATE="2026-10-01T12:00:00Z",
            GIT_COMMITTER_DATE="2026-10-01T12:00:00Z",
        ),
    )
    row = dict(
        repo="org/repo",
        number=1,
        title="Work",
        body="",
        url="https://github.com/org/repo/pull/1",
        person="Rae",
        ticket_mentions=[],
        state="MERGED",
        mergedAt="2026-10-01T06:00:00Z",
        isDraft=False,
    )

    def collect(config, start, end, out, **kwargs):
        out.mkdir(parents=True)
        (out / "repo.json").write_text(
            json.dumps(
                [
                    row,
                    {
                        **row,
                        "number": 2,
                        "state": "OPEN",
                        "mergedAt": None,
                        "isDraft": True,
                        "requested_reviewers": ["Bo"],
                    },
                ]
            )
        )
        return {"complete": True, "repositories": [{"file": "repo.json"}]}

    def github(*args):
        return {
            "data": {
                "repository": {
                    "defaultBranchRef": {
                        "name": "main",
                        "target": {
                            "oid": "abc",
                            "checkSuites": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            },
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(report, "collect", collect)
    monkeypatch.setattr(report, "gh_json", github)
    out = tmp_path / "out"
    daily.prepare(
        {
            "repos": ["org/repo"],
            "teams": ["BE"],
            "timezone": "Asia/Jerusalem",
            "hour": 8,
        },
        mirror,
        out,
        {},
        datetime(2026, 10, 2, 6, tzinfo=timezone.utc),
    )
    assert len(json.loads((out / "inventory.json").read_text())) == 2
    assert (
        json.loads((out / "tickets.json").read_text())[0]["metadata"]["status"]
        == "Done"
    )
    messages = "".join(p.read_text() for p in (out / "messages").glob("*.md"))
    assert "org/repo#1" in messages and "org/repo#2" in messages and "Bo" in messages
    assert "BE-1" in messages


def test_successful_cutoff_is_idempotent():
    state = {"last_cutoff": "2026-10-02T05:00:00+00:00"}

    class Slack:
        def post(self, *args):
            pytest.fail("already published")

    daily.publish(
        [("01.md", "top")],
        state,
        "2026-10-02T05:00:00+00:00",
        Slack(),
        lambda s: pytest.fail("no new state"),
    )


def test_compact_discussions_page_all_channels_and_keep_inline_evidence(monkeypatch):
    def node(n):
        return {
            "databaseId": n,
            "body": "Actual review",
            "createdAt": "2026-10-01T10:00:00Z",
            "updatedAt": "2026-10-01T10:00:00Z",
            "url": f"https://github.com/example/{n}",
            "author": {"login": "rae"},
        }

    calls = []

    def github(*args):
        calls.append(args)
        if args[1] == "graphql" and "reviewThreads" in args[args.index("-f") + 1]:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [
                                    {
                                        "id": "thread",
                                        "comments": {
                                            "nodes": [
                                                {
                                                    **node(4),
                                                    "body": "Fix this invariant",
                                                }
                                            ],
                                            "pageInfo": {"hasNextPage": False},
                                        },
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            }
        if args[1] == "graphql":
            second = "commentsCursor=next" in args
            pr = {}
            pr["comments"] = {
                "nodes": [node(2 if second else 1)],
                "pageInfo": {"hasNextPage": not second, "endCursor": "next"},
            }
            if not second:
                pr["reviews"] = {
                    "totalCount": 1,
                    "nodes": [
                        {
                            **node(3),
                            "submittedAt": "2026-10-01T10:00:00Z",
                            "state": "CHANGES_REQUESTED",
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            return {"data": {"repository": {"pullRequest": pr}}}
        return [[{"body": "Fix this invariant", "created_at": "2026-10-01T10:00:00Z"}]]

    monkeypatch.setattr(report, "gh_json", github)
    evidence = report.event_evidence(
        "org/repo",
        1,
        datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 2, tzinfo=timezone.utc),
        compact=True,
    )
    assert len(evidence["comments"]) == 2
    assert evidence["reviews"][0]["state"] == "CHANGES_REQUESTED"
    assert evidence["review_comments"][0]["body"] == "Fix this invariant"
    assert len(calls) == 3


def test_unreviewed_pr_needs_no_rest_discussion_requests(monkeypatch):
    def github(*args):
        assert args[:2] == ("api", "graphql")
        page = {
            "nodes": [],
            "totalCount": 0,
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
        return {
            "data": {"repository": {"pullRequest": {"comments": page, "reviews": page}}}
        }

    monkeypatch.setattr(report, "gh_json", github)
    assert report.compact_discussions("org/repo", 1)["review_comments"] == []


@pytest.mark.parametrize(
    "date,start,end,hours",
    [
        (
            "2026-10-05T09:00:00+03:00",
            "2026-10-02T05:00:00+00:00",
            "2026-10-05T05:00:00+00:00",
            72,
        ),
        (
            "2026-10-06T09:00:00+03:00",
            "2026-10-05T05:00:00+00:00",
            "2026-10-06T05:00:00+00:00",
            24,
        ),
        (
            "2026-10-26T09:00:00+02:00",
            "2026-10-23T05:00:00+00:00",
            "2026-10-26T06:00:00+00:00",
            73,
        ),
        (
            "2026-10-03T09:00:00+03:00",
            "2026-10-01T05:00:00+00:00",
            "2026-10-02T05:00:00+00:00",
            24,
        ),
    ],
)
def test_weekday_window_keeps_friday_workday_and_weekend(date, start, end, hours):
    a, b = daily.window(
        datetime.fromisoformat(date), "Asia/Jerusalem", 8, weekdays=[0, 1, 2, 3, 4]
    )
    assert a.isoformat() == start
    assert b.isoformat() == end
    assert (b - a).total_seconds() == hours * 3600
