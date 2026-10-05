"""Attribute the next PR action from collected activity, never mutable updatedAt."""

from datetime import datetime, timedelta


def classify_waiting(pr, as_of, people, *, review_comment_urls=()):
    """Optional review URLs come from reading collected issue-comment bodies."""
    names = {login.casefold(): name for login, name in people.items()}

    def name(login):
        return names.get((login or "").casefold(), login or "unknown")

    author = (pr.get("author") or {}).get("login")
    result = {
        "as_of": as_of.isoformat(),
        "kind": "unknown",
        "people": [],
        "reason": "incomplete_activity",
        "evidence": [],
    }
    if pr.get("state") != "OPEN":
        return {**result, "kind": "closed", "reason": "no_longer_open"}
    snapshot = pr.get("activity_snapshot") or {}
    if not snapshot.get("complete") or not author:
        return result

    def instant(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def actors(event):
        return [a.casefold() for a in event.get("actors", []) if a]

    def human(event):
        return not event.get("automated") and any(
            not a.endswith("[bot]") for a in actors(event)
        )

    events = [
        e for e in snapshot["events"] if e.get("at") and instant(e["at"]) <= as_of
    ]
    review_urls = set(review_comment_urls)
    comment_urls = {e.get("url") for e in events if e["kind"] == "comment"}
    if not review_urls <= comment_urls:
        raise ValueError("Issue-comment review must cite a collected current comment")
    events = [
        {**e, "kind": "review", "state": "COMMENTED"}
        if e["kind"] == "comment" and e.get("url") in review_urls
        else e
        for e in events
    ]
    movement = [e for e in events if e["kind"] == "commit" or human(e) or not actors(e)]
    movement.append(
        {
            "kind": "opened",
            "at": pr["createdAt"],
            "actors": [author],
            "url": pr["url"],
        }
    )
    latest = max(movement, key=lambda e: instant(e["at"]))
    result["last_movement"] = latest
    if as_of - instant(latest["at"]) >= timedelta(days=4):
        return {
            **result,
            "kind": "author",
            "people": [name(author)],
            "reason": "inactive_four_days",
            "evidence": [latest],
        }

    # Private drafts, dismissed reviews and self-reviews do not hand off work.
    reviews = [
        e
        for e in events
        if (
            e["kind"] == "inline_comment"
            or (
                e["kind"] == "review"
                and e.get("state") in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
            )
        )
        and actors(e)
        and author.casefold() not in actors(e)
    ]
    if reviews:
        review = max(reviews, key=lambda e: instant(e["at"]))
        followups = [
            e
            for e in events
            if e["kind"]
            in {"commit", "comment", "inline_comment", "HeadRefForcePushedEvent"}
            and instant(e["at"]) > instant(review["at"])
        ]
        if not any(author.casefold() in actors(e) for e in followups):
            if any(
                not actors(e) or e.get("identity_complete") is False for e in followups
            ):
                return {
                    **result,
                    "reason": "unattributed_followup",
                    "evidence": [review],
                }
            return {
                **result,
                "kind": "author",
                "people": [name(author)],
                "reason": "review_without_author_followup",
                "evidence": [review],
            }

    requested = [
        name(r["login"])
        if r.get("login")
        else r.get("name") or r.get("slug") or "unknown team"
        for r in pr.get("reviewRequests", [])
    ]
    if requested and not pr.get("isDraft"):
        return {
            **result,
            "kind": "reviewer",
            "people": requested,
            "reason": "requested_review",
            "evidence": [e for e in events if e["kind"] == "ReviewRequestedEvent"][-1:],
        }
    return {
        **result,
        "kind": "active",
        "reason": "no_observed_review_dependency",
        "evidence": [latest],
    }
