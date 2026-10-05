from copy import deepcopy
from datetime import datetime, timezone

import pytest

from issueclaw.pr_waiting import classify_waiting


NOW = datetime(2026, 10, 5, 5, tzinfo=timezone.utc)
PEOPLE = {"author": "Rae", "reviewer": "Bo", "other": "Kai"}


def pr(*events, requests=None):
    return {
        "state": "OPEN",
        "author": {"login": "AUTHOR"},
        "createdAt": "2026-10-01T06:00:00Z",
        "url": "https://github.com/org/repo/pull/1",
        "reviewRequests": requests or [],
        "activity_snapshot": {"complete": True, "events": list(events)},
    }


def event(kind, at, actor: str | None = "reviewer", **extra):
    return {
        "kind": kind,
        "at": at,
        "actors": [actor],
        "url": "https://github.com/event",
        **extra,
    }


def test_pending_review_names_requested_person_and_team_without_guessing():
    row = pr(
        requests=[{"login": "REVIEWER"}, {"slug": "backend", "name": "Backend team"}]
    )
    result = classify_waiting(row, NOW, PEOPLE)
    assert result["kind"] == "reviewer"
    assert result["people"] == ["Bo", "Backend team"]
    assert result["reason"] == "requested_review"


def test_review_without_author_followup_waits_on_author_even_with_other_request():
    row = pr(
        event("review", "2026-10-04T06:00:00Z", state="CHANGES_REQUESTED"),
        requests=[{"login": "other"}],
    )
    result = classify_waiting(row, NOW, PEOPLE)
    assert result["kind"] == "author"
    assert result["people"] == ["Rae"]
    assert result["reason"] == "review_without_author_followup"
    assert result["evidence"][0]["at"] == "2026-10-04T06:00:00Z"


@pytest.mark.parametrize("kind", ["comment", "inline_comment", "commit"])
def test_author_followup_clears_author_wait_and_hands_pending_request_to_reviewer(kind):
    row = pr(
        event("review", "2026-10-03T06:00:00Z", state="APPROVED"),
        event(kind, "2026-10-04T06:00:00Z", actor="AUTHOR"),
        requests=[{"login": "other"}],
    )
    result = classify_waiting(row, NOW, PEOPLE)
    assert result["kind"] == "reviewer"
    assert result["people"] == ["Kai"]
    row["reviewRequests"] = []
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "active"


def test_four_elapsed_days_overrides_reviewer_wait_despite_bot_and_metadata_churn():
    row = pr(
        event("commit", "2026-10-01T05:00:00Z", actor="author"),
        event("comment", "2026-10-05T04:00:00Z", actor="github-actions[bot]"),
        requests=[{"login": "reviewer"}],
    )
    row["createdAt"] = "2026-09-01T00:00:00Z"
    row["updatedAt"] = "2026-10-05T04:59:00Z"
    result = classify_waiting(row, NOW, PEOPLE)
    assert result["kind"] == "author"
    assert result["reason"] == "inactive_four_days"
    assert result["last_movement"]["at"] == "2026-10-01T05:00:00Z"
    row["activity_snapshot"]["events"][0]["at"] = "2026-10-01T05:00:01Z"
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "reviewer"


def test_new_review_request_is_movement_but_draft_is_not_a_reviewer_wait():
    row = pr(
        event("ReviewRequestedEvent", "2026-10-05T04:00:00Z", actor="author"),
        requests=[{"login": "reviewer"}],
    )
    row["createdAt"] = "2026-09-01T00:00:00Z"
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "reviewer"
    row["isDraft"] = True
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "active"


def test_latest_review_not_older_review_controls_followup():
    row = pr(
        event("review", "2026-10-02T06:00:00Z", state="COMMENTED"),
        event("comment", "2026-10-03T06:00:00Z", actor="author"),
        event("review", "2026-10-04T06:00:00Z", state="APPROVED"),
    )
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "author"


@pytest.mark.parametrize("state", ["PENDING", "DISMISSED"])
def test_pending_dismissed_and_self_reviews_are_not_external_feedback(state):
    row = pr(
        event("review", "2026-10-04T06:00:00Z", state=state),
        event("review", "2026-10-04T07:00:00Z", actor="author", state="COMMENTED"),
    )
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "active"


def test_missing_snapshot_and_unattributed_followup_cannot_prove_author_absence():
    row = pr(
        event("review", "2026-10-04T06:00:00Z", state="COMMENTED"),
        event("commit", "2026-10-04T07:00:00Z", actor=None),
    )
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "unknown"
    del row["activity_snapshot"]
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "unknown"


def test_unknown_commit_author_stays_uncertain_even_with_known_committer():
    row = pr(
        event("review", "2026-10-04T06:00:00Z", state="COMMENTED"),
        event(
            "commit", "2026-10-04T07:00:00Z", actor="web-flow", identity_complete=False
        ),
    )
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "unknown"


def test_inline_reviewer_reply_is_feedback_even_without_new_formal_review():
    row = pr(
        event("review", "2026-10-02T06:00:00Z", state="APPROVED"),
        event("commit", "2026-10-03T06:00:00Z", actor="author"),
        event("inline_comment", "2026-10-04T06:00:00Z"),
    )
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "author"


def test_closed_pr_is_not_waiting_and_classification_does_not_mutate_sources():
    row = pr()
    original = deepcopy(row)
    classify_waiting(row, NOW, PEOPLE)
    assert row == original
    row["state"] = "MERGED"
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "closed"


def test_review_posted_as_issue_comment_can_return_action_to_author():
    row = pr(event("comment", "2026-10-04T06:00:00Z"), requests=[{"login": "reviewer"}])
    assert classify_waiting(row, NOW, PEOPLE)["kind"] == "reviewer"
    result = classify_waiting(
        row, NOW, PEOPLE, review_comment_urls=["https://github.com/event"]
    )
    assert result["kind"] == "author"
    assert result["people"] == ["Rae"]
    with pytest.raises(ValueError, match="collected current comment"):
        classify_waiting(
            row, NOW, PEOPLE, review_comment_urls=["https://github.com/invented"]
        )


def test_graphql_bot_login_without_suffix_does_not_reset_inactivity():
    row = pr(
        event("comment", "2026-10-05T04:00:00Z", actor="github-actions", automated=True)
    )
    row["createdAt"] = "2026-09-01T00:00:00Z"
    assert classify_waiting(row, NOW, PEOPLE)["reason"] == "inactive_four_days"
