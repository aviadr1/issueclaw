import json
from unittest.mock import patch

import pytest

from issueclaw import briefing_experiment as experiment
from issueclaw import briefing_experiment_trace as tracing


def test_prepare_discards_prior_reports_media_and_uses_same_editorial_config(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    config = {
        "repos": ["org/repo"],
        "teams": ["BE"],
        "channel": "C1",
        "instructions": "old",
        "timezone": "UTC",
        "delivery_format": "canvas",
    }
    data = {name: [] for name in experiment.SOURCE_FILES}
    data.update(
        {
            "briefing-config.json": config,
            "window.json": {
                "start": "2026-10-21T08:00:00+00:00",
                "resume": True,
                "timezone": "UTC",
            },
            "delivery.json": {
                "cutoff": "2026-10-22T08:00:00+00:00",
                "files": ["01-toplevel.md"],
                "inventory_files": ["002-inventory.md"],
            },
        }
    )
    for name, value in data.items():
        experiment.write_json(source / name, value)
    for folder in ("pr-records", "evidence", "messages", "learnings"):
        (source / folder).mkdir()
    (source / "messages/002-inventory.md").write_text("org/repo#1")
    (source / "messages/01-toplevel.md").write_text("previous report")
    (source / "report.md").write_text("previous report")
    (source / "learnings/video.mp4").write_bytes(b"old media")
    current = tmp_path / "config.json"
    experiment.write_json(current, {**config, "instructions": "new labels"})
    hashes = experiment.prepare(source, tmp_path / "one", current)
    assert hashes == experiment.prepare(source, tmp_path / "two", current)
    out = tmp_path / "one"
    assert not (out / "report.md").exists()
    assert not (out / "messages/01-toplevel.md").exists()
    assert not (out / "learnings").exists()
    window = json.loads((out / "window.json").read_text())
    assert window["instructions"] == "new labels"
    assert window["start"] == data["window.json"]["start"]
    assert window["resume"] is False
    with pytest.raises(ValueError, match="new directory"):
        experiment.prepare(source, out, current)


def test_costs_use_final_results_once_and_keep_missing_unknown(tmp_path):
    (tmp_path / "generation.log").write_text(
        'not json\n{"type":"assistant","total_cost_usd":99}\n'
        '{"type":"result","total_cost_usd":1.25,"usage":{"output_tokens":10}}\n'
    )
    stage = tmp_path / "split/ci"
    stage.mkdir(parents=True)
    (stage / "run.log").write_text('{"type":"result","total_cost_usd":2.5}\n')
    assert experiment.cost_metrics(tmp_path)["reported_cost_usd"] == 3.75
    (tmp_path / "revision-1.log").write_text("interrupted\n")
    result = experiment.cost_metrics(tmp_path)
    assert result["reported_cost_usd"] is None
    assert result["known_cost_subtotal_usd"] == 3.75
    assert not result["cost_complete"]


def test_required_tracing_fails_before_model_without_key(tmp_path):
    with patch.dict(tracing.os.environ, {"BRIEFING_REQUIRE_TRACE": "1"}, clear=True):
        with pytest.raises(RuntimeError, match="requires"):
            tracing.claude_tracing(tmp_path, "ci")


def test_tracing_sessions_and_state_are_isolated_and_receipt_has_no_key(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "bundle").mkdir(parents=True)
    (plugin / "bundle/dispatch.js").write_text("")
    env = {
        "CC_LANGSMITH_API_KEY": "secret-key",
        "LEARNING_TRACE_PLUGIN": str(plugin),
        "CC_LANGSMITH_PROJECT": "experiment",
        "BRIEFING_EXPERIMENT_ARM": "split",
    }
    with patch.dict(tracing.os.environ, env, clear=True):
        args1, env1 = tracing.claude_tracing(tmp_path / "ci", "ci")
        args2, env2 = tracing.claude_tracing(tmp_path / "learning", "learning")
    assert args1[-1] != args2[-1]
    assert env1["STATE_FILE"] != env2["STATE_FILE"]
    receipt = (tmp_path / "ci/ci.trace.json").read_text()
    assert "secret-key" not in receipt
    assert json.loads(receipt)["metadata"]["stage"] == "ci"
