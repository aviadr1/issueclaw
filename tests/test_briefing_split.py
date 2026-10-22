"""Exercise real assembly and validation with evidence-shaped frozen inputs."""

import json
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from issueclaw import briefing_split as split


def prepared(tmp_path, changes=1):
    out = tmp_path / "evidence"
    out.mkdir()
    inventory = [
        {
            "repo": "org/service",
            "number": n,
            "url": f"https://github.com/org/service/pull/{n}",
            "title": f"Capability {n}",
            "person": "Example Author",
            "state": "merged",
        }
        for n in range(1, changes + 1)
    ]
    info = {
        "title": "Daily briefing",
        "start": "2026-10-21T05:00:00+00:00",
        "end_exclusive": "2026-10-22T05:00:00+00:00",
        "snapshot_as_of": "2026-10-22T05:01:00+00:00",
        "timezone": "Asia/Jerusalem",
        "delivery_format": "canvas",
        "slack_summary_format": "titles",
        "canvas_inventory": "merged",
        "review_video": True,
    }
    split.write_json(out / "window.json", info)
    split.write_json(out / "inventory.json", inventory)
    split.write_json(
        out / "delivery.json",
        {
            "canvas_title": "Daily briefing",
            "files": ["01-toplevel.md"],
            "inventory_files": ["002-inventory.md"],
        },
    )
    split.write_json(
        out / "review-learning-evidence.json",
        {"review_events": 0, "inline_review_comments": 0, "comments": []},
    )
    (out / "messages").mkdir()
    (out / "messages" / "002-inventory.md").write_text(
        "\n".join(f"org/service#{r['number']}" for r in inventory)
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Frozen evidence. State what readers should do and why.")
    return out, prompt, inventory


def plan_for(inventory):
    return {
        "changes": [
            {
                "id": f"change-{i}",
                "prs": [f"{r['repo']}#{r['number']}"],
                "focus": r["title"],
            }
            for i, r in enumerate(inventory, 1)
        ],
        "queue_prs": [],
        "learning_notes": "Compare reusable correctness mechanisms.",
        "invitation": "Open today's briefing for the mechanisms behind the changes.",
        "coverage": [
            {
                "pr": f"{r['repo']}#{r['number']}",
                "placement": "story",
                "reason": r["title"],
            }
            for r in inventory
        ],
        "notes": "All configured repositories were inspected.",
    }


def packet_for(name):
    value = {
        "markdown": "",
        "claims": [],
        "coverage": [],
        "notes": "Frozen sources inspected.",
    }
    if name.startswith("change-"):
        value["markdown"] = (
            f"### {name}: bounded writes — Leads: Example Author\n\nOlder writes cannot replace a newer version."
        )
    elif name == "queue":
        value.update(
            markdown="## Waiting on people\n\n### No verified review waits\n\n## Active work\n\n### No active work selected",
            review_selection={
                "pr": None,
                "reason": "The current inventory contains no open PRs.",
            },
            review_markdown="",
        )
    elif name == "ci":
        value["markdown"] = "### All good — no CI action needed"
    elif name == "learning":
        value.update(
            markdown="### Merged learning: reject stale writes\n\nFor you — Apply a technique: compare versions before replacing state. [Example](https://github.com/org/service/pull/1)",
            selection_audit={
                "candidates": [
                    {
                        "prs": ["org/service#1"],
                        "idea": "Reject stale writes",
                        "reuse": "Cache refreshes",
                        "evidence": ["https://github.com/org/service/pull/1"],
                        "tradeoff": "Requires comparable versions",
                        "decision": "selected",
                        "reason": "Reusable invariant",
                    }
                ],
                "advisor_summary": "Preferred the correctness invariant to generic tooling.",
            },
            review_learning={
                "review_events": 0,
                "inline_review_comments": 0,
                "inspected_prs": [],
                "patterns": [],
                "no_pattern_reason": "No dated review comment bodies in this frozen sample.",
            },
        )
    return value


def test_split_runs_fresh_bounded_workers_and_preserves_fragments(tmp_path):
    out, prompt, inventory = prepared(tmp_path, changes=4)
    protected = split.evidence_fingerprint(out)
    calls = []
    lock = threading.Lock()
    active = peak = 0

    def run(args, *, cwd, stdout, stderr, env, timeout, check):
        nonlocal active, peak
        name = cwd.name
        with lock:
            calls.append((name, args, cwd))
            if name not in {"curator", "reader"}:
                active += 1
                peak = max(peak, active)
        if name not in {"curator", "reader"}:
            time.sleep(0.04)
        result = (
            plan_for(inventory)
            if name == "curator"
            else {"issues": [], "summary": "Checked evidence and actions."}
            if name == "reader"
            else packet_for(name)
        )
        split.write_json(cwd / "result.json", result)
        stdout.write(json.dumps({"type": "result", "total_cost_usd": 0.1}) + "\n")
        with lock:
            if name not in {"curator", "reader"}:
                active -= 1

    with (
        patch.object(split.subprocess, "run", side_effect=run),
        patch.object(
            split.briefing_experiment_trace,
            "claude_tracing",
            return_value=(["--trace-test"], {"TRACE_TEST": "1"}),
        ) as tracing,
    ):
        split.generate(out, prompt)
    assert 2 <= peak <= split.MAX_WORKERS
    assert len(calls) == 9
    assert len({cwd for _, _, cwd in calls}) == 9
    assert tracing.call_count == 9
    assert any(name == "ci" for name, _, _ in calls)
    assert all(
        "--max-budget-usd" in args and "--trace-test" in args for _, args, _ in calls
    )
    report = (out / "report.md").read_text(encoding="utf-8")
    for name, _, _ in calls:
        if name not in {"curator", "reader"}:
            assert packet_for(name)["markdown"] in report
    assert "2026-10-21 08:00 +0300 (inclusive)" in report
    split.assert_unchanged(protected)
    split.daily.validate_output(out)


def test_plan_rejects_historical_or_open_pr_in_daily_changes(tmp_path):
    _, _, inventory = prepared(tmp_path)
    plan = plan_for(inventory)
    plan["changes"][0]["prs"] = ["org/service#999"]
    with pytest.raises(ValueError, match="daily merged"):
        split.validate_plan(plan, inventory)
    plan = plan_for(inventory)
    inventory[0]["state"] = "open"
    with pytest.raises(ValueError, match="daily merged"):
        split.validate_plan(plan, inventory)


def test_claims_require_action_scope_and_evidence(tmp_path):
    _, _, inventory = prepared(tmp_path)
    packet = packet_for("ci")
    packet["claims"] = [
        {
            "claim": "Tests passed",
            "status": "observed",
            "reader_action": "none",
            "scope": "default branch",
            "unknowns": [],
        }
    ]
    with pytest.raises(ValueError, match="evidence"):
        split.validate_packet("ci", packet, inventory)


def test_failed_agent_keeps_trace_and_detects_evidence_mutation(tmp_path):
    out, _, _ = prepared(tmp_path)
    protected = split.evidence_fingerprint(out)

    def run(*args, **kwargs):
        kwargs["stdout"].write("partial stream remains\n")
        (out / "inventory.json").write_text("[]")
        raise subprocess.TimeoutExpired("claude", split.AGENT_TIMEOUT)

    with (
        patch.object(split.subprocess, "run", side_effect=run),
        patch.object(
            split.briefing_experiment_trace, "claude_tracing", return_value=([], {})
        ),
    ):
        with pytest.raises(RuntimeError, match="Prepared evidence changed"):
            split.run_agent(out, "ci", "Inspect CI", protected)
    assert (out / "split/ci/run.log").read_text() == "partial stream remains\n"
    assert split.read_json(out / "split/ci/execution.json")["error"]


def test_reader_repairs_only_targeted_worker(tmp_path):
    out, prompt, inventory = prepared(tmp_path)
    seen = []

    def agent(out, name, instructions, protected):
        seen.append(name)
        if name == "curator":
            return plan_for(inventory)
        if name == "reader":
            return {
                "issues": [
                    {
                        "worker": "ci",
                        "problem": "Missing uncertainty",
                        "repair": "Name the required gate access gap.",
                    }
                ],
                "summary": "One issue",
            }
        result = packet_for("ci" if name == "ci-repair" else name)
        if name == "ci-repair":
            result["markdown"] = (
                "### CI status unverified — restore gate access\n\nThe required check was not collected."
            )
        return result

    with patch.object(split, "run_agent", side_effect=agent):
        split.generate(out, prompt)
    assert seen[-1] == "ci-repair"
    assert "change-1-repair" not in seen
    report = (out / "report.md").read_text(encoding="utf-8")
    assert packet_for("change-1")["markdown"] in report
    assert "restore gate access" in report
    assert "All good" not in report


def test_reader_cannot_trigger_unbounded_repair_round(tmp_path):
    out, prompt, inventory = prepared(tmp_path)

    def agent(out, name, instructions, protected):
        if name == "curator":
            return plan_for(inventory)
        if name == "reader":
            return {
                "issues": [
                    {
                        "worker": worker,
                        "problem": "Wrong fact",
                        "repair": "Fix with source",
                    }
                    for worker in ["change-1", "queue", "ci", "learning"]
                ]
            }
        return packet_for(name)

    with patch.object(split, "run_agent", side_effect=agent):
        with pytest.raises(RuntimeError, match="experiment budget bound"):
            split.generate(out, prompt)


def save_stage(out, name, result):
    directory = out / "split" / name
    directory.mkdir(parents=True)
    split.write_json(directory / "result.json", result)
    split.write_json(
        directory / "execution.json", {"elapsed_seconds": 1, "error": None}
    )
    (directory / "run.log").write_text('{"type":"result","total_cost_usd":0.1}\n')


def saved_drafts(out, prompt, inventory):
    directory = out / "split"
    directory.mkdir()
    (directory / "contract.md").write_text(
        prompt.read_text(encoding="utf-8"), encoding="utf-8"
    )
    plan = plan_for(inventory)
    split.write_json(directory / "plan.json", plan)
    save_stage(out, "curator", plan)
    for name in [r["id"] for r in plan["changes"]] + ["queue", "ci", "learning"]:
        packet = packet_for(name)
        if name == "change-1":
            packet["claims"] = [
                {
                    "claim": "Older writes are rejected",
                    "evidence": ["https://github.com/org/service/pull/1"],
                    "status": "merged",
                    "reader_action": "technique",
                    "scope": "Writes with comparable versions",
                    "unknowns": "Production rollout is not verified.",
                }
            ]
        save_stage(out, name, packet)


def test_resume_reuses_complete_drafts_and_normalizes_without_rewriting_raw_output(
    tmp_path,
):
    out, prompt, inventory = prepared(tmp_path)
    protected = split.evidence_fingerprint(out)
    saved_drafts(out, prompt, inventory)
    original_files = {
        p: p.read_bytes() for p in (out / "split").rglob("*") if p.is_file()
    }

    def reader(out, name, instructions, protected):
        assert name == "reader"
        return {"issues": [], "summary": "Verified material claims and limits."}

    with patch.object(split, "run_agent", side_effect=reader) as runner:
        split.generate(out, prompt, resume=True)
    runner.assert_called_once()
    assert packet_for("change-1")["markdown"] in (out / "report.md").read_text(
        encoding="utf-8"
    )
    assert all(p.read_bytes() == content for p, content in original_files.items())
    claims = split.read_json(out / "split/claims.json")
    assert claims["change-1"][0]["unknowns"] == ["Production rollout is not verified."]
    assert (
        split.read_json(out / "split/change-1/normalization.json")["changes"][0]["path"]
        == "claims[0].unknowns"
    )
    split.assert_unchanged(protected)
    split.daily.validate_output(out)


def test_resume_does_not_repeat_existing_reader_or_repair(tmp_path):
    out, prompt, inventory = prepared(tmp_path)
    saved_drafts(out, prompt, inventory)
    save_stage(
        out,
        "reader",
        {
            "issues": [
                {
                    "worker": "ci",
                    "problem": "Missing gate evidence",
                    "repair": "State the verification action.",
                }
            ],
            "summary": "One targeted correction.",
        },
    )
    packet = packet_for("ci")
    packet["markdown"] = (
        "### CI status unverified — restore required gate access\n\nRequired evidence is missing."
    )
    save_stage(out, "ci-repair", packet)
    with patch.object(split, "run_agent") as runner:
        split.generate(out, prompt, resume=True)
    runner.assert_not_called()
    assert packet["markdown"] in (out / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["contract", "missing", "invalid", "incomplete"])
def test_resume_rejects_changed_contract_or_unusable_saved_stage(tmp_path, failure):
    out, prompt, inventory = prepared(tmp_path)
    saved_drafts(out, prompt, inventory)
    directory = out / "split/change-1"
    if failure == "contract":
        prompt.write_text("Different editorial rules.")
    elif failure == "missing":
        (directory / "result.json").unlink()
    elif failure == "invalid":
        packet = split.read_json(directory / "result.json")
        packet["claims"][0]["unknowns"] = ""
        split.write_json(directory / "result.json", packet)
    else:
        split.write_json(directory / "execution.json", {"error": "Timed out"})
    with patch.object(split, "run_agent") as runner:
        with pytest.raises((ValueError, FileNotFoundError)):
            split.generate(out, prompt, resume=True)
    runner.assert_not_called()
