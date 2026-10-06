from datetime import datetime, timedelta, timezone

import pytest
import click

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
        author={"login": "AUTHOR"},
        state="OPEN",
        mergedAt=None,
        updatedAt="2026-01-01T00:00:00Z",
        createdAt="2026-01-01T00:00:00Z",
        isDraft=True,
        reviewRequests=[{"login": "REVIEWER"}],
        reviewDecision="REVIEW_REQUIRED",
        headRefOid="abc",
        statusCheckRollup=[],
    )

    def github(*args):
        if args[:2] == ("api", "graphql"):
            page = {"nodes": [], "pageInfo": {"hasNextPage": False}}
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "state": "OPEN",
                            "headRefOid": "abc",
                            "commits": page,
                            "timelineItems": page,
                        }
                    }
                }
            }
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
        {"repos": ["org/repo"], "people": {"reviewer": "Rae", "author": "Bo"}},
        start,
        end,
        tmp_path,
        include_open=True,
    )
    assert manifest["complete"]
    import json

    rows = json.loads((tmp_path / "org--repo.json").read_text())
    assert rows[0]["bucket"] == "draft"
    assert rows[0]["person"] == "Bo"
    assert rows[0]["requested_reviewers"] == ["Rae"]
    assert rows[0]["waiting"]["kind"] == "author"
    assert rows[0]["waiting"]["reason"] == "inactive_four_days"


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


@pytest.mark.parametrize("delivery_format", ["thread", "canvas"])
def test_prepare_audits_daily_merges_carryover_and_changed_done_tickets(
    monkeypatch, tmp_path, delivery_format
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
        reviews=review_record(1)["reviews"],
        review_comments=review_record(1)["review_comments"],
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
            "delivery_format": delivery_format,
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
    if delivery_format == "canvas":
        delivery = json.loads((out / "delivery.json").read_text())
        assert delivery["files"] == ["01-toplevel.md"]
        assert delivery["inventory_files"]
        assert delivery["canvas_title"] == "Backend learning briefing — 2026-10-02"
    review_evidence = json.loads((out / "review-learning-evidence.json").read_text())
    assert review_evidence["review_events"] == 2
    assert review_evidence["inline_review_comments"] == 2
    assert {r["pr"] for r in review_evidence["comments"]} == {
        "org/repo#1",
        "org/repo#2",
    }


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


def test_coverage_audit_requires_each_pr_once():
    rows = [{"repo": "org/repo", "number": 1}, {"repo": "org/repo", "number": 2}]
    good = [
        {"pr": "org/repo#1", "placement": "story", "reason": "Adds a capability"},
        {"pr": "org/repo#2", "placement": "inventory", "reason": "Old draft"},
    ]
    daily.validate_coverage(rows, good)
    with pytest.raises(RuntimeError, match="coverage"):
        daily.validate_coverage(rows, good[:1])
    with pytest.raises(RuntimeError, match="coverage"):
        daily.validate_coverage(rows, [good[0], good[0], good[1]])
    with pytest.raises(RuntimeError, match="coverage"):
        daily.validate_coverage(rows, [good[0], {**good[1], "reason": ""}])


def test_delivery_ledger_drops_old_receipts_but_keeps_cutoff_idempotency():
    old = "2026-10-01T05:00:00+00:00"
    current = "2026-10-02T05:00:00+00:00"
    state = {"last_cutoff": old, "messages": {old + "/01.md": {"ts": "old"}}}

    class Slack:
        def post(self, *args):
            return "new"

    daily.publish([("01.md", "new")], state, current, Slack(), lambda s: None)
    assert state["messages"] == {current + "/01.md": {"ts": "new"}}
    daily.publish(
        [("01.md", "old")],
        state,
        old,
        Slack(),
        lambda s: pytest.fail("Already completed cutoff must not be written"),
    )


def test_github_failure_preserves_actionable_stderr(monkeypatch):
    import subprocess

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, ["gh", "api", "graphql"], stderr="API rate limit exceeded"
        )

    monkeypatch.setattr(report.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="API rate limit exceeded"):
        report.gh_json("api", "graphql")


def review_record(number, body="Retrying the whole operation duplicates its effects"):
    return {
        "repo": "org/repo",
        "number": number,
        "reviews": [{"body": "", "html_url": "formal"}],
        "review_comments": [
            {
                "body": body,
                "html_url": f"https://github.com/org/repo/pull/{number}#discussion_r{number}",
                "created_at": "2026-10-01T10:00:00Z",
                "user": {"login": "rae"},
                "body_available_at_cutoff": True,
            }
        ],
    }


def test_review_learning_uses_dated_bodies_and_counts_empty_formal_reviews():
    rows = [review_record(1), review_record(2)]
    rows[1]["review_comments"][0]["body_available_at_cutoff"] = False
    rows[0]["review_snapshot"] = [{"body": "Current, outside history"}]
    evidence = daily.review_learning_evidence(rows)
    assert evidence["review_events"] == 2
    assert evidence["inline_review_comments"] == 2
    assert [r["pr"] for r in evidence["comments"]] == ["org/repo#1"]
    assert evidence["comments"][0]["reviewer"] == "rae"


def learning_audit():
    return {
        "review_events": 2,
        "inline_review_comments": 2,
        "inspected_prs": ["org/repo#1", "org/repo#2"],
        "patterns": [
            {
                "summary": "Retries duplicate side effects",
                "shared_solution": "Test retries against the shared effect boundary",
                "evidence": [
                    {
                        "pr": f"org/repo#{n}",
                        "url": review_record(n)["review_comments"][0]["html_url"],
                    }
                    for n in (1, 2)
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "defect", ["false_zero", "fabricated_link", "same_pr", "missing_citations"]
)
def test_review_audit_blocks_unsupported_learning_claims(defect):
    evidence = daily.review_learning_evidence([review_record(1), review_record(2)])
    audit = learning_audit()
    top = "**What to fix once** " + " ".join(
        e["url"] for e in audit["patterns"][0]["evidence"]
    )
    if defect == "false_zero":
        audit["review_events"] = 0
    elif defect == "fabricated_link":
        audit["patterns"][0]["evidence"][0]["url"] = "invented"
    elif defect == "same_pr":
        audit["patterns"][0]["evidence"][1] = audit["patterns"][0]["evidence"][0]
    else:
        top = "**What to fix once** Retry safely."
    with pytest.raises(RuntimeError, match="Review learning audit"):
        daily.validate_review_learning(evidence, audit, top)


def test_review_audit_accepts_cited_independent_reviews_and_quiet_windows():
    evidence = daily.review_learning_evidence([review_record(1), review_record(2)])
    audit = learning_audit()
    top = "**What to fix once** " + " ".join(
        e["url"] for e in audit["patterns"][0]["evidence"]
    )
    daily.validate_review_learning(evidence, audit, top)
    quiet = {
        "review_events": 0,
        "inline_review_comments": 0,
        "inspected_prs": [],
        "patterns": [],
        "no_pattern_reason": "No dated review evidence",
    }
    daily.validate_review_learning(
        daily.review_learning_evidence([]), quiet, "Quiet day"
    )
    with pytest.raises(RuntimeError, match="CI claims must name"):
        daily.validate_review_learning(evidence, audit, top + " CI: all green")


def prepared_draft(tmp_path):
    import json

    (tmp_path / "messages").mkdir()
    files = {
        "window.json": {"already_posted": False},
        "delivery.json": {
            "cutoff": "2026-10-05T05:00:00+00:00",
            "files": ["01-toplevel.md", "02-inventory.md"],
        },
        "inventory.json": [],
        "coverage.json": [],
        "review-learning-evidence.json": {
            "review_events": 0,
            "inline_review_comments": 0,
            "comments": [],
        },
        "review-learning.json": {
            "review_events": 0,
            "inline_review_comments": 0,
            "inspected_prs": [],
            "patterns": [],
            "no_pattern_reason": "Quiet history",
        },
    }
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "coverage.md").write_text("No inventory in this quiet window")
    (tmp_path / "messages/02-inventory.md").write_text("Quiet inventory")
    (tmp_path / "messages/01-toplevel.md").write_text("word " * 551)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Write a concrete learning brief")
    return prompt


def test_generation_repairs_validation_failure_without_recollecting(
    monkeypatch, tmp_path
):
    prompt = prepared_draft(tmp_path)
    calls = []

    def claude(args, **kwargs):
        calls.append(args)
        assert "exceeds 550 words" in args[2]
        (tmp_path / "messages/01-toplevel.md").write_text(
            "No new work. Review carry-over."
        )

    monkeypatch.setattr(daily.subprocess, "run", claude)
    daily.generate(tmp_path, prompt)
    assert len(calls) == 1
    assert daily.validate_output(tmp_path)[0][1] == "No new work. Review carry-over."


def test_generation_stops_after_two_failed_revisions(monkeypatch, tmp_path):
    prompt = prepared_draft(tmp_path)
    calls = []
    monkeypatch.setattr(
        daily.subprocess, "run", lambda args, **kwargs: calls.append(args)
    )
    with pytest.raises(RuntimeError, match="exceeds 550 words"):
        daily.generate(tmp_path, prompt)
    assert len(calls) == 2


def test_generation_never_rewrites_pending_artifact(monkeypatch, tmp_path):
    prompt = prepared_draft(tmp_path)
    (tmp_path / "window.json").write_text('{"resume": true}')
    monkeypatch.setattr(
        daily.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("immutable pending thread"),
    )
    daily.generate(
        tmp_path, prompt, revision_notes="Must not rewrite a pending publication"
    )
    assert len((tmp_path / "messages/01-toplevel.md").read_text().split()) == 551


def test_generator_cannot_rewrite_prepared_cutoff_or_inventory(monkeypatch, tmp_path):
    prompt = prepared_draft(tmp_path)

    def claude(*args, **kwargs):
        (tmp_path / "window.json").write_text('{"already_posted": true}')

    monkeypatch.setattr(daily.subprocess, "run", claude)
    with pytest.raises(RuntimeError, match="Prepared evidence changed"):
        daily.generate(tmp_path, prompt)


def canvas_draft(tmp_path):
    import json

    prompt = prepared_draft(tmp_path)
    (tmp_path / "window.json").write_text(
        json.dumps({"delivery_format": "canvas", "timezone": "Asia/Jerusalem"})
    )
    (tmp_path / "delivery.json").write_text(
        json.dumps(
            {
                "cutoff": "2026-10-05T05:00:00+00:00",
                "files": ["01-toplevel.md"],
                "inventory_files": ["02-inventory.md"],
                "canvas_title": "Backend learning briefing — 2026-10-05",
            }
        )
    )
    (tmp_path / "messages/01-toplevel.md").write_text(
        "A short TLDR with the people and next decisions."
    )
    (tmp_path / "messages/02-inventory.md").write_text(
        "MERGED\n• Quiet inventory", encoding="utf-8"
    )
    (tmp_path / "report.md").write_text("Full report " * 350)
    return prompt


def test_canvas_full_report_exceeds_550_words_and_contains_complete_inventory(tmp_path):
    canvas_draft(tmp_path)
    messages = daily.validate_output(tmp_path)
    assert len(messages) == 1
    assert len((tmp_path / "report.md").read_text().split()) > 550
    assert "- Quiet inventory" in (tmp_path / "canvas.md").read_text()
    assert "Full report" in (tmp_path / "canvas.md").read_text()


def test_title_summary_uses_canvas_topics_and_fresh_invitation_without_prose(tmp_path):
    canvas_draft(tmp_path)
    daily.configure_delivery(
        tmp_path, {"delivery_format": "canvas", "slack_summary_format": "titles"}
    )
    report = """# Briefing date
## What changed
### Payments checks load only payments routes — Leads: Rae Chen
Long explanation stays in the Canvas.
```markdown
## An example inside code is not a topic
```
## Waiting on people
Work queue.
### Active work
Recent progress.
## CI
Observed checks.
## Learning
### What to fix once: reuse the due-work harness
Practical advice.
"""
    (tmp_path / "report.md").write_text(report)
    (tmp_path / "canvas-invitation.md").write_text(
        "Today's rabbit hole has guardrails. Open the Canvas for the full story."
    )
    messages = daily.validate_output(tmp_path)
    assert len(messages) == 1
    assert [line for line in messages[0][1].splitlines() if line.startswith("- ")] == [
        "- Payments checks load only payments routes — Leads: Rae Chen",
        "- Waiting on people",
        "- Active work",
        "- CI",
        "- What to fix once: reuse the due-work harness",
    ]
    assert "Long explanation" not in messages[0][1]
    assert "inside code" not in messages[0][1]
    assert messages[0][1].endswith("Open the Canvas for the full story.")
    assert (tmp_path / "messages/01-toplevel.md").read_text().strip() == messages[0][1]
    assert daily.validate_output(tmp_path) == messages


def test_title_summary_keeps_every_title_even_when_the_list_exceeds_180_words(tmp_path):
    canvas_draft(tmp_path)
    daily.configure_delivery(
        tmp_path, {"delivery_format": "canvas", "slack_summary_format": "titles"}
    )
    titles = [f"Capability {i} " + "specific behavior " * 10 for i in range(10)]
    (tmp_path / "report.md").write_text("\n".join("### " + title for title in titles))
    (tmp_path / "canvas-invitation.md").write_text(
        "Open the Canvas. The plot has indexes."
    )
    text = daily.validate_output(tmp_path)[0][1]
    assert len(text.split()) > 180
    assert sum(line.startswith("- ") for line in text.splitlines()) == len(titles)


@pytest.mark.parametrize(
    "invitation",
    ["", "First paragraph\nSecond paragraph", "word " * 26, " Same invitation. "],
)
def test_title_summary_rejects_missing_long_multiline_or_repeated_invitation(
    tmp_path, invitation
):
    import json

    canvas_draft(tmp_path)
    daily.configure_delivery(
        tmp_path, {"delivery_format": "canvas", "slack_summary_format": "titles"}
    )
    info = json.loads((tmp_path / "window.json").read_text())
    info["previous_canvas_invitation"] = "same invitation."
    daily.write_json(tmp_path / "window.json", info)
    (tmp_path / "report.md").write_text("## CI\nTests passed.")
    (tmp_path / "canvas-invitation.md").write_text(invitation)
    with pytest.raises(RuntimeError, match="Canvas invitation"):
        daily.validate_output(tmp_path)


def test_completed_delivery_records_invitation_for_the_next_briefing():
    state = {"messages": {"cutoff/01.md": {"ts": "1"}}}
    daily.publish(
        [("01.md", "Previously delivered")],
        state,
        "cutoff",
        None,
        lambda _: None,
        canvas_invitation="Read on. The plot has indexes.",
    )
    assert state["last_canvas_invitation"] == "Read on. The plot has indexes."


def test_title_message_links_the_invitation_to_the_confirmed_canvas_url():
    message = "**Briefing**\n\n- One topic\n\nOpen the Canvas. The plot has indexes."
    linked = daily.canvas_message_link(
        message, "https://slack.com/docs/F123", titles=True
    )
    assert (
        linked
        == "**Briefing**\n\n- One topic\n\n[Open the Canvas. The plot has indexes.](https://slack.com/docs/F123)"
    )
    assert (
        daily.canvas_message_link("Short paragraph", "https://slack.com/docs/F123")
        == "Short paragraph\n[Full report in Slack Canvas](https://slack.com/docs/F123)"
    )


def test_curated_canvas_keeps_full_evidence_but_appends_only_merges(tmp_path):
    import json

    canvas_draft(tmp_path)
    daily.configure_delivery(
        tmp_path, {"delivery_format": "canvas", "canvas_inventory": "merged"}
    )
    rows = [
        {
            "repo": "org/repo",
            "number": n,
            "state": state,
            "url": f"https://github.com/org/repo/pull/{n}",
            "title": title,
            "person": "Rae",
        }
        for n, state, title in (
            (1, "merged", "New capability"),
            (2, "open", "Old open work"),
            (3, "draft", "Old draft work"),
        )
    ]
    daily.write_json(tmp_path / "inventory.json", rows)
    daily.write_json(
        tmp_path / "coverage.json",
        [
            {
                "pr": f"org/repo#{r['number']}",
                "placement": "inventory",
                "reason": "Retained in evidence",
            }
            for r in rows
        ],
    )
    evidence_text = "MERGED\n• org/repo#1\nOPEN\n• org/repo#2 Old open work\nDRAFT\n• org/repo#3 Old draft work\nRELEVANT TICKETS (current mirror)\n• Old ticket dump"
    inventory_file = tmp_path / "messages/02-inventory.md"
    inventory_file.write_text(evidence_text, encoding="utf-8")
    daily.validate_output(tmp_path)
    canvas = (tmp_path / "canvas.md").read_text()
    assert "New capability" in canvas
    assert "https://github.com/org/repo/pull/1" in canvas
    assert "Old open work" not in canvas
    assert "Old draft work" not in canvas
    assert "Old ticket dump" not in canvas
    assert inventory_file.read_text(encoding="utf-8") == evidence_text
    assert len(json.loads((tmp_path / "inventory.json").read_text())) == 3


def test_curated_canvas_rejects_an_unprioritized_open_pr_dump(tmp_path):
    canvas_draft(tmp_path)
    daily.configure_delivery(
        tmp_path, {"delivery_format": "canvas", "canvas_inventory": "merged"}
    )
    rows = [
        {
            "repo": "org/repo",
            "number": n,
            "state": "open",
            "url": f"https://github.com/org/repo/pull/{n}",
            "title": "Open work",
            "person": "Rae",
        }
        for n in range(1, 10)
    ]
    daily.write_json(tmp_path / "inventory.json", rows)
    daily.write_json(
        tmp_path / "coverage.json",
        [
            {
                "pr": f"org/repo#{r['number']}",
                "placement": "queue",
                "reason": "Review requested",
            }
            for r in rows
        ],
    )
    (tmp_path / "messages/02-inventory.md").write_text(
        "\n".join(f"org/repo#{r['number']}" for r in rows)
    )
    (tmp_path / "report.md").write_text("\n".join(r["url"] for r in rows))
    with pytest.raises(RuntimeError, match="at most 8 open/draft PRs"):
        daily.validate_output(tmp_path)


def test_canvas_only_limits_the_tldr_and_digest_covers_full_report(tmp_path):
    canvas_draft(tmp_path)
    messages = daily.validate_output(tmp_path)
    digest = daily.delivery_digest(tmp_path, messages)
    (tmp_path / "report.md").write_text("Different full report")
    daily.validate_output(tmp_path)
    assert daily.delivery_digest(tmp_path, messages) != digest
    (tmp_path / "messages/01-toplevel.md").write_text("word " * 181)
    with pytest.raises(RuntimeError, match="TLDR exceeds 180 words"):
        daily.validate_output(tmp_path)


@pytest.mark.parametrize("failure", ["files_info", "uncertain_create"])
def test_canvas_receipt_is_durable_and_retry_never_creates_twice(
    monkeypatch, tmp_path, failure
):
    import copy
    import json
    import httpx
    from issueclaw import slack_canvas

    canvas_draft(tmp_path)
    daily.validate_output(tmp_path)
    state = {}
    durable = []
    calls = []

    def save(value):
        durable.append(copy.deepcopy(value))

    def handle(request):
        method = request.url.path.split("/")[-1]
        calls.append(method)
        if method == "canvases.create":
            assert durable[-1]["canvas"]["receipt"]["pending"] is True
            assert json.loads(request.content)["channel_id"] == "C123"
            if failure == "uncertain_create":
                raise httpx.ReadTimeout("lost response")
            return httpx.Response(200, json={"ok": True, "canvas_id": "F123"})
        assert method == "files.info"
        assert durable[-1]["canvas"]["receipt"]["canvas_id"] == "F123"
        if calls.count("files.info") == 1:
            return httpx.Response(200, json={"ok": False, "error": "missing_scope"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"permalink": "https://team.slack.com/docs/F123"},
            },
        )

    monkeypatch.setattr(
        slack_canvas,
        "make_client",
        lambda token: httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        ),
    )
    with pytest.raises((httpx.ReadTimeout, click.ClickException)):
        daily.publish_canvas(tmp_path, {"channel": "C123"}, state, save, "test-token")
    if failure == "uncertain_create":
        with pytest.raises(click.ClickException, match="unknown"):
            daily.publish_canvas(
                tmp_path, {"channel": "C123"}, state, save, "test-token"
            )
    else:
        assert (
            daily.publish_canvas(
                tmp_path, {"channel": "C123"}, state, save, "test-token"
            )
            == "https://team.slack.com/docs/F123"
        )
        assert (
            durable[-1]["canvas"]["receipt"]["url"]
            == "https://team.slack.com/docs/F123"
        )
    assert calls.count("canvases.create") == 1


def test_operator_notes_revise_a_valid_canvas_preview(monkeypatch, tmp_path):
    prompt = canvas_draft(tmp_path)
    daily.validate_output(tmp_path)
    calls = []

    def claude(args, **kwargs):
        calls.append(args)
        assert "Explain the dev measurement accurately" in args[2]
        (tmp_path / "report.md").write_text(
            "A corrected full report.", encoding="utf-8"
        )

    monkeypatch.setattr(daily.subprocess, "run", claude)
    daily.generate(
        tmp_path, prompt, revision_notes="Explain the dev measurement accurately"
    )
    assert len(calls) == 1
    assert (
        (tmp_path / "canvas.md")
        .read_text(encoding="utf-8")
        .startswith("A corrected full report.")
    )
