import json
from pathlib import Path

import pytest
import yaml

from issueclaw import briefing_replay as replay
from tests.test_daily_briefing import canvas_draft


@pytest.fixture
def snapshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    canvas_draft(source)
    for name in replay.SOURCE_FILES:
        if not (source / name).exists():
            replay.write_json(source / name, {})
    for folder in ("pr-records", "evidence"):
        (source / folder).mkdir()
        (source / folder / "raw.md").write_text("Frozen evidence")
    config = {
        "channel": "C1",
        "repos": ["org/repo"],
        "teams": ["team"],
        "delivery_format": "canvas",
        "slack_summary_format": "actions",
    }
    replay.write_json(source / "briefing-config.json", config)
    config_path = tmp_path / "config.json"
    replay.write_json(config_path, config)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Write the briefing in /tmp/daily-briefing.")
    editorial = tmp_path / "editorial.md"
    editorial.write_text("Explain who needs to do what.")
    return source, tmp_path / "output", config_path, prompt, editorial


def test_prepare_copies_only_evidence_and_resets_old_modes(snapshot):
    source, out, config, _, _ = snapshot
    info = json.loads((source / "window.json").read_text())
    info.update(
        already_posted=True,
        resume=True,
        slack_summary_format="titles",
        canvas_inventory="none",
    )
    replay.write_json(source / "window.json", info)
    original = {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    manifest = replay.prepare(source, out, config)
    assert not (out / "report.md").exists()
    assert not (out / "messages/01-toplevel.md").exists()
    assert not (out / "coverage.json").exists()
    assert (out / "evidence/raw.md").read_text() == "Frozen evidence"
    actual = json.loads((out / "window.json").read_text())
    assert actual["slack_summary_format"] == "actions"
    assert "canvas_inventory" not in actual
    assert not actual["resume"] and not actual["already_posted"]
    assert manifest["source_evidence_sha256"] == replay.manifest_digest(
        manifest["source_files"]
    )
    assert all((source / name).read_bytes() == data for name, data in original.items())


def test_evidence_hash_is_independent_of_editorial_config(snapshot):
    source, out, config, _, _ = snapshot
    first = replay.prepare(source, out, config)
    value = json.loads(config.read_text())
    value.update(
        title="New title", instructions="Different framing", delivery_format="thread"
    )
    replay.write_json(config, value)
    second_out = out.with_name("second")
    second = replay.prepare(source, second_out, config)
    assert first["source_evidence_sha256"] == second["source_evidence_sha256"]
    assert first["resolved_config_sha256"] != second["resolved_config_sha256"]
    assert "delivery_format" not in json.loads((second_out / "window.json").read_text())
    assert json.loads((second_out / "delivery.json").read_text())["files"] == [
        "01-toplevel.md",
        "02-inventory.md",
    ]


@pytest.mark.parametrize("field", ["channel", "repos", "teams"])
def test_rejects_wrong_identity_before_creating_output(snapshot, field):
    source, out, config, _, _ = snapshot
    value = json.loads(config.read_text())
    value[field] = "other" if field == "channel" else ["other"]
    replay.write_json(config, value)
    with pytest.raises(ValueError, match="different repositories"):
        replay.prepare(source, out, config)
    assert not out.exists()


def test_accepts_one_legacy_manifest_but_rejects_missing_or_ambiguous(snapshot):
    source, out, config, _, _ = snapshot
    canonical = source / "briefing-config.json"
    saved = canonical.read_bytes()
    canonical.unlink()
    with pytest.raises(ValueError, match="unambiguous"):
        replay.prepare(source, out, config)
    (source / "config-123-1.json").write_bytes(saved)
    (source / "config-123-2.json").write_bytes(saved)
    with pytest.raises(ValueError, match="unambiguous"):
        replay.prepare(source, out, config)
    (source / "config-123-2.json").unlink()
    replay.prepare(source, out, config)


@pytest.mark.parametrize(
    "name", ["../escape.md", "..\\escape.md", "C:secret", "01-toplevel.md", "", "."]
)
def test_rejects_unsafe_inventory(snapshot, name):
    source, out, config, _, _ = snapshot
    delivery = json.loads((source / "delivery.json").read_text())
    delivery["inventory_files"] = [name]
    replay.write_json(source / "delivery.json", delivery)
    with pytest.raises(ValueError, match="inventory filename"):
        replay.prepare(source, out, config)
    assert not out.exists()


def test_rejects_output_reuse_and_nested_output(snapshot):
    source, out, config, _, _ = snapshot
    for target in (source, source / "nested"):
        with pytest.raises(ValueError, match="new directory"):
            replay.prepare(source, target, config)
    out.mkdir()
    with pytest.raises(ValueError, match="new directory"):
        replay.prepare(source, out, config)


def test_manifest_checks_deleted_or_changed_inputs_without_scanning_traces(
    snapshot, monkeypatch
):
    source, out, config, _, _ = snapshot
    expected = replay.prepare(source, out, config)["prepared_files"]
    (out / "text-traces/langsmith_queue").mkdir(parents=True)
    (out / "text-traces/langsmith_queue/transient.lock").write_text("ephemeral")
    monkeypatch.setattr(
        Path, "rglob", lambda *args: pytest.fail("must not scan outputs")
    )
    assert replay.changed_inputs(out, expected) == []
    (out / "inventory.json").unlink()
    (out / "evidence/raw.md").write_text("changed")
    assert set(replay.changed_inputs(out, expected)) == {
        "inventory.json",
        "evidence/raw.md",
    }


def test_run_uses_current_actions_writer_and_validator(snapshot, monkeypatch):
    source, out, _, _, _ = snapshot
    calls = []
    monkeypatch.delenv("BRIEFING_REQUIRE_TRACE", raising=False)
    monkeypatch.delenv("LEARNING_TRACE_PLUGIN", raising=False)

    def claude(args, **kwargs):
        calls.append(args)
        assert "# Worked example: a readable action-first briefing" in args[2]
        assert "Consumer editorial instructions" in args[2]
        assert not (out / "report.md").exists()
        (out / "report.md").write_text("A fresh report based on the quiet window.")
        for name in ("coverage.json", "coverage.md", "review-learning.json"):
            (out / name).write_bytes((source / name).read_bytes())
        replay.write_json(
            out / "slack-summary.json", {"needs_attention": [], "for_awareness": []}
        )
        kwargs["stdout"].write('{"type":"result","total_cost_usd":1.25}\n')

    monkeypatch.setattr(replay.daily.subprocess, "run", claude)
    replay.run(*snapshot)
    assert len(calls) == 1
    assert (
        "No verified actions needed." in (out / "messages/01-toplevel.md").read_text()
    )
    metrics = json.loads((out / "replay-metrics.json").read_text())
    assert metrics["status"] == "passed"
    assert metrics["evidence_unchanged"] and metrics["cost_complete"]
    assert metrics["reported_cost_usd"] == 1.25


@pytest.mark.parametrize("mutate", [False, True])
def test_failed_generation_always_preserves_metrics_and_checks_evidence(
    snapshot, monkeypatch, mutate
):
    _, out, _, _, _ = snapshot

    def failed(*args):
        (out / "generation.log").write_text("partial output")
        if mutate:
            (out / "inventory.json").unlink()
        raise RuntimeError("generation failed")

    monkeypatch.setattr(replay.daily, "generate", failed)
    with pytest.raises(
        RuntimeError,
        match="Prepared evidence changed" if mutate else "generation failed",
    ):
        replay.run(*snapshot)
    metrics = json.loads((out / "replay-metrics.json").read_text())
    assert metrics["status"] == "failed"
    assert metrics["evidence_unchanged"] is not mutate
    assert metrics["reported_cost_usd"] is None
    assert metrics["changed_input_files"] == (["inventory.json"] if mutate else [])


def test_replay_workflow_has_read_only_permissions_and_no_publish_credentials():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/briefing-replay.yml"
    workflow = yaml.safe_load(path.read_text())
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert set(workflow[True]["workflow_call"]["secrets"]) == {
        "ANTHROPIC_API_KEY",
        "LANGSMITH_API_KEY",
    }
    steps = workflow["jobs"]["replay"]["steps"]
    run = next(
        s for s in steps if s.get("name") == "Generate and validate without publication"
    )
    assert "issueclaw.briefing_replay" in run["run"]
    assert "GH_TOKEN" not in run["env"] and "GITHUB_TOKEN" not in run["env"]
    assert run["env"]["BRIEFING_REQUIRE_TRACE"] == "1"
    assert all(
        not s.get("with", {}).get("persist-credentials", True)
        for s in steps
        if s.get("uses", "").startswith("actions/checkout@")
    )
