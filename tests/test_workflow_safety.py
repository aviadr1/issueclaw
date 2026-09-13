"""Installed writer policies must compose safely across all workflow roles."""

from pathlib import Path

import pytest
import yaml

from issueclaw.workflow_templates import bundled_template_text, workflow_template_files


@pytest.mark.parametrize("name", workflow_template_files())
def test_all_writers_share_non_canceling_lock(name):
    workflow = yaml.safe_load(bundled_template_text(name))
    assert workflow["concurrency"] == {
        "group": "linear-git-sync",
        "cancel-in-progress": False,
        "queue": "max",
    }


def test_documents_are_not_discarded_by_caller():
    workflow = yaml.safe_load(bundled_template_text("issueclaw-webhook.yaml"))
    assert workflow["jobs"]["apply-webhook"]["if"] == (
        "${{ !(github.event.client_payload.type == 'Comment' && "
        "github.event.client_payload.data.issueId == null) }}"
    )


def test_reusable_webhook_does_not_sleep_per_event():
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1] / ".github/workflows/webhook.yml"
        ).read_text()
    )
    steps = workflow["jobs"]["apply-webhook"]["steps"]
    assert not any("sleep " in step.get("run", "") for step in steps)


def test_reusable_queue_sweep_pushes_only_when_queue_files_exist():
    text = (
        Path(__file__).resolve().parents[1] / ".github/workflows/queue-sweep.yml"
    ).read_text()
    assert "files=(linear/new/**/*.md)" in text
    assert 'echo "has_queue=false"' in text
    assert 'echo "has_queue=true"' in text
    assert "if: steps.queue.outputs.has_queue == 'true'" in text
    assert "run: issueclaw push" in text
