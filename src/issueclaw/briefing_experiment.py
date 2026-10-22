"""Run one arm of a text-only, unpublished briefing comparison on frozen evidence."""

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from issueclaw import daily_briefing as daily
from issueclaw.briefing_config import load_config, prepared_config

SOURCE_FILES = (
    "briefing-config.json",
    "window.json",
    "inventory.json",
    "reading-index.json",
    "review-learning-evidence.json",
    "tickets.json",
    "context.json",
    "ci.json",
    "delivery.json",
)


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def fingerprints(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def prepare(source: Path, out: Path, config_path: Path):
    """Copy only collection outputs; never seed either writer with an earlier report."""
    if out.exists():
        raise ValueError("Experiment output must be a new directory")
    config = load_config(config_path)
    prepared_config(config, source)  # reject another audience's snapshot
    out.mkdir(parents=True)
    for name in SOURCE_FILES:
        shutil.copyfile(source / name, out / name)
    for folder in ("pr-records", "evidence"):
        shutil.copytree(source / folder, out / folder)
    (out / "messages").mkdir()
    delivery = json.loads((out / "delivery.json").read_text())
    for name in delivery.get("inventory_files", delivery["files"][1:]):
        if Path(name).name != name or name == "01-toplevel.md":
            raise ValueError("Invalid prepared inventory filename")
        shutil.copyfile(source / "messages" / name, out / "messages" / name)
    # Freeze time, state, identity, CI and ticket evidence. Apply the SAME current
    # editorial configuration to both arms, including the recently clarified labels.
    info = json.loads((out / "window.json").read_text())
    info.update(already_posted=False, resume=False)
    write_json(out / "window.json", info)
    write_json(out / "briefing-config.json", config)
    daily.configure_delivery(out, config)
    return fingerprints(out)


def cost_metrics(out: Path) -> dict:
    """Use one final CLI result per invocation; never sum repeated usage events."""
    logs = sorted(out.glob("generation.log")) + sorted(out.glob("revision-*.log"))
    logs += sorted((out / "split").rglob("run.log"))
    invocations = []
    for path in logs:
        terminal = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                terminal = event
        invocations.append(
            {
                "log": path.relative_to(out).as_posix(),
                "has_terminal_result": terminal is not None,
                "reported_cost_usd": (terminal or {}).get("total_cost_usd"),
                "duration_ms": (terminal or {}).get("duration_ms"),
                "duration_api_ms": (terminal or {}).get("duration_api_ms"),
                "usage": (terminal or {}).get("usage"),
                "model_usage": (terminal or {}).get("modelUsage"),
                "session_id": (terminal or {}).get("session_id"),
                "is_error": (terminal or {}).get("is_error"),
            }
        )
    known = [
        row["reported_cost_usd"]
        for row in invocations
        if isinstance(row["reported_cost_usd"], (int, float))
    ]
    complete = bool(invocations) and len(known) == len(invocations)
    return {
        "invocations": invocations,
        "cost_complete": complete,
        "reported_cost_usd": sum(known) if complete else None,
        "known_cost_subtotal_usd": sum(known),
        "cost_basis": "Claude CLI final result per invocation, including CLI-managed subagents/advisor; not an invoice. Missing results are unknown, never zero.",
    }


def run(arm: str, source: Path, out: Path, config: Path, prompt: Path, editorial: Path):
    started = time.monotonic()
    prepared = prepare(source, out, config)
    frozen_digest = hashlib.sha256(
        json.dumps(prepared, sort_keys=True).encode()
    ).hexdigest()
    text = prompt.read_text(encoding="utf-8").replace(
        "/tmp/daily-briefing", str(out.resolve())
    )
    text += "\n\nConsumer editorial instructions (same in both experimental arms):\n"
    text += editorial.read_text(encoding="utf-8")
    text += "\n\nThis is a text-only private experiment. Do not make videos or publish. Retain the review walkthrough as text when eligible. Do not claim a video exists.\n"
    actual_prompt = out / "experiment-prompt.md"
    actual_prompt.write_text(text, encoding="utf-8")
    os.environ["BRIEFING_EXPERIMENT_ARM"] = arm
    metrics = {
        "arm": arm,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "evidence_run": os.environ.get("BRIEFING_EVIDENCE_RUN"),
        "ci_run": os.environ.get("GITHUB_RUN_ID"),
        "input_sha256": frozen_digest,
        "input_files": prepared,
        "editorial_sha256": hashlib.sha256(editorial.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
        "status": "running",
        "videos": False,
        "slack_publication": False,
    }
    write_json(out / "experiment-metrics.json", metrics)
    generation_started = time.monotonic()
    try:
        if arm == "baseline":
            daily.generate(out, actual_prompt)
        else:
            from issueclaw.briefing_split import generate

            generate(out, actual_prompt)
        daily.validate_output(out)
        metrics["status"] = "passed"
    except Exception as error:
        metrics.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        metrics["generation_seconds"] = time.monotonic() - generation_started
        current = fingerprints(out)
        changed = [
            name for name, digest in prepared.items() if current.get(name) != digest
        ]
        metrics.update(
            evidence_unchanged=not changed,
            changed_input_files=changed,
            elapsed_seconds=time.monotonic() - started,
            completed_at=datetime.now(timezone.utc).isoformat(),
            **cost_metrics(out),
        )
        if changed:
            metrics.update(status="failed", error="Prepared evidence changed")
        write_json(out / "experiment-metrics.json", metrics)
        if changed:
            raise RuntimeError("Prepared evidence changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("baseline", "split"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--editorial", type=Path, required=True)
    args = parser.parse_args()
    run(args.arm, args.source, args.out, args.config, args.prompt, args.editorial)


if __name__ == "__main__":
    main()
