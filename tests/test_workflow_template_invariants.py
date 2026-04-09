"""Invariants for managed workflow templates."""

from issueclaw.workflow_templates import bundled_template_text


def test_webhook_template_debounces_but_keeps_issue_comment_updates_realtime() -> None:
    """INVARIANT: webhook stub drops only safe low-signal events."""
    text = bundled_template_text("issueclaw-webhook.yaml")

    assert "cancel-in-progress: true" in text
    assert "group: linear-git-webhook" in text
    assert "github.event.client_payload.type == 'Document'" in text
    assert "github.event.client_payload.data.issueId == null" in text
    assert "github.event.client_payload.action == 'update'" not in text


def test_sync_template_is_10min_backstop_and_never_cancels_runs() -> None:
    """INVARIANT: periodic pull remains the eventual-consistency correctness path."""
    text = bundled_template_text("issueclaw-sync.yaml")

    assert "cron: '*/10 * * * *'" in text
    assert "cancel-in-progress: false" in text
    assert "group: linear-git-sync-pull" in text


def test_push_template_isolated_from_webhook_cancellation() -> None:
    """INVARIANT: push concurrency group is separate from webhook debounce."""
    text = bundled_template_text("issueclaw-push.yaml")

    assert "group: linear-git-push" in text
    assert "cancel-in-progress: false" in text


def test_queue_sweep_template_exists_and_shares_push_group() -> None:
    """INVARIANT: queue sweeper is installed and serialized with push."""
    text = bundled_template_text("issueclaw-queue-sweep.yaml")

    assert "cron: '*/10 * * * *'" in text
    assert "group: linear-git-push" in text
    assert "queue-sweep.yml@main" in text
