"""Invariants for managed workflow templates."""

from pathlib import Path
import re

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


def test_concurrency_groups_are_isolated_by_workflow_role() -> None:
    """INVARIANT: webhook debounce cannot cancel push/sync runs."""

    def _group(text: str) -> str:
        m = re.search(r"^\s*group:\s*([^\n]+)\s*$", text, flags=re.MULTILINE)
        assert m is not None
        return m.group(1).strip()

    push_group = _group(bundled_template_text("issueclaw-push.yaml"))
    sync_group = _group(bundled_template_text("issueclaw-sync.yaml"))
    webhook_group = _group(bundled_template_text("issueclaw-webhook.yaml"))
    sweep_group = _group(bundled_template_text("issueclaw-queue-sweep.yaml"))

    assert push_group == "linear-git-push"
    assert sweep_group == "linear-git-push"
    assert sync_group == "linear-git-sync-pull"
    assert webhook_group == "linear-git-webhook"
    assert len({push_group, sync_group, webhook_group}) == 3


def test_reusable_queue_sweep_pushes_only_when_queue_files_exist() -> None:
    """INVARIANT: queue sweeper is a guarded recovery path, not unconditional push."""
    workflow_file = (
        Path(__file__).resolve().parents[1] / ".github/workflows/queue-sweep.yml"
    )
    text = workflow_file.read_text()

    assert "files=(linear/new/**/*.md)" in text
    assert 'echo "has_queue=false"' in text
    assert 'echo "has_queue=true"' in text
    assert "if: steps.queue.outputs.has_queue == 'true'" in text
    assert "run: issueclaw push" in text
