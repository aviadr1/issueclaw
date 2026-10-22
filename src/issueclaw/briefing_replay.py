"""Replay the production single writer against frozen evidence without publishing."""

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from issueclaw import daily_briefing as daily
from issueclaw.briefing_config import load_config, prepared_config
from issueclaw.briefing_generation_trace import cost_metrics

SOURCE_FILES = (
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


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def manifest_digest(value: dict) -> str:
    return digest(json.dumps(value, sort_keys=True).encode())


def safe_file(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
        raise ValueError(f"Symlink in evidence: {name}")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or unsafe evidence: {name}")
    return path


def fingerprints(root: Path, names) -> dict[str, str]:
    # Inspect only recorded inputs, never live tracing/upload directories.
    return {name: digest(safe_file(root, name).read_bytes()) for name in sorted(names)}


def prepare(source: Path, out: Path, config_path: Path) -> dict:
    if out.exists() or out.resolve().is_relative_to(source.resolve()):
        raise ValueError("Replay output must be a new directory outside the source")
    config = load_config(config_path)
    canonical = source / "briefing-config.json"
    legacy = sorted(
        p
        for p in source.glob("config-*.json")
        if re.fullmatch(r"config-\d+-\d+\.json", p.name)
    )
    if not canonical.exists() and len(legacy) != 1:
        raise ValueError("Replay requires one unambiguous source configuration")
    source_config = canonical if canonical.exists() else legacy[0]
    safe_file(source, source_config.name)
    prepared_config(config, source)  # Verify audience identity before copying.
    names: list[str] = list(SOURCE_FILES)
    for folder in ("pr-records", "evidence"):
        directory = source / folder
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"Missing or unsafe evidence directory: {folder}")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Symlink in evidence: {path.name}")
            if path.is_file():
                names.append(path.relative_to(source).as_posix())
    delivery = json.loads(
        safe_file(source, "delivery.json").read_text(encoding="utf-8")
    )
    inventory = delivery.get("inventory_files", delivery["files"][1:])
    for name in inventory:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", "..", "01-toplevel.md"}
            or any(c in name for c in "/\\:")
        ):
            raise ValueError("Invalid prepared inventory filename")
        names.append("messages/" + name)
    original = fingerprints(source, names)
    out.mkdir(parents=True)
    for folder in ("pr-records", "evidence", "messages"):
        (out / folder).mkdir()
    for name in names:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe_file(source, name), target)
    if fingerprints(out, names) != original:
        raise ValueError("Source evidence changed while copying")
    info = json.loads((out / "window.json").read_text(encoding="utf-8"))
    # Reset prior editorial modes before applying current configuration. Preserve
    # collection dates, identity, CI and ticket evidence exactly as collected.
    for key in (
        "delivery_format",
        "review_video",
        "slack_summary_format",
        "canvas_inventory",
    ):
        info.pop(key, None)
    info.update(already_posted=False, resume=False)
    write_json(out / "window.json", info)
    delivery.pop("canvas_title", None)
    delivery["files"] = ["01-toplevel.md", *inventory]
    write_json(out / "delivery.json", delivery)
    write_json(out / "briefing-config.json", config)
    daily.configure_delivery(out, config)
    prepared = fingerprints(out, [*names, "briefing-config.json"])
    return {
        "source_evidence_sha256": manifest_digest(original),
        "source_files": original,
        "source_config_sha256": digest(source_config.read_bytes()),
        "prepared_files": prepared,
        "resolved_config_sha256": prepared["briefing-config.json"],
    }


def changed_inputs(out: Path, expected: dict) -> list[str]:
    changed = []
    for name, expected_digest in expected.items():
        try:
            if digest(safe_file(out, name).read_bytes()) != expected_digest:
                changed.append(name)
        except (OSError, ValueError):
            changed.append(name)
    return changed


def run(source: Path, out: Path, config: Path, prompt: Path, editorial: Path):
    started = time.monotonic()
    prompt_bytes, editorial_bytes = prompt.read_bytes(), editorial.read_bytes()
    manifest = prepare(source, out, config)
    text = prompt_bytes.decode("utf-8").replace(
        "/tmp/daily-briefing", str(out.resolve())
    )
    text += "\n\nConsumer editorial instructions:\n" + editorial_bytes.decode("utf-8")
    text += "\n\nThis is a private text-only replay. Do not make videos or publish. Retain the review walkthrough as text when eligible. Do not claim a video exists.\n"
    actual_prompt = out / "replay-prompt.md"
    actual_prompt.write_text(text, encoding="utf-8")
    manifest["prepared_files"][actual_prompt.name] = digest(actual_prompt.read_bytes())
    editorial_inputs = {
        "resolved_config_sha256": manifest["resolved_config_sha256"],
        "editorial_sha256": digest(editorial_bytes),
        "prompt_sha256": digest(prompt_bytes),
    }
    metrics = {
        **manifest,
        **editorial_inputs,
        "editorial_inputs_sha256": manifest_digest(editorial_inputs),
        "prepared_sha256": manifest_digest(manifest["prepared_files"]),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "evidence_run": os.environ.get("BRIEFING_EVIDENCE_RUN"),
        "ci_run": os.environ.get("GITHUB_RUN_ID"),
        "variant": os.environ.get("BRIEFING_REPLAY_VARIANT", "single-writer"),
        "status": "running",
        "videos": False,
        "slack_publication": False,
    }
    write_json(out / "replay-metrics.json", metrics)
    generation_started = time.monotonic()
    try:
        daily.generate(out, actual_prompt)
        daily.validate_output(out)
        metrics["status"] = "passed"
    except Exception as error:
        metrics.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        changed = changed_inputs(out, manifest["prepared_files"])
        metrics.update(
            generation_seconds=time.monotonic() - generation_started,
            elapsed_seconds=time.monotonic() - started,
            completed_at=datetime.now(timezone.utc).isoformat(),
            evidence_unchanged=not changed,
            changed_input_files=changed,
            **cost_metrics(out),
        )
        if changed:
            metrics.update(status="failed", error="Prepared evidence changed")
        write_json(out / "replay-metrics.json", metrics)
        if changed:
            raise RuntimeError("Prepared evidence changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "out", "config", "prompt", "editorial"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.out, args.config, args.prompt, args.editorial)


if __name__ == "__main__":
    main()
