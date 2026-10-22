"""Recover missing final visual review from tool evidence, retaining reviewed cache keys."""

import argparse
import json
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Call:
    name: str
    start: int
    end: int | None = None
    path: str = ""
    background: bool = False
    started_at: float | None = None
    ended_at: float | None = None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def successful(block):
    content = block.get("content")
    if block.get("is_error") or not content:
        return False
    parts = content if isinstance(content, list) else [content]
    for part in parts:
        if isinstance(part, dict):
            if part.get("error") or "error" in part.get("type", ""):
                return False
            part = part.get("text", "")
        if isinstance(part, str) and part.lstrip().startswith(
            ("Error:", "<tool_use_error>")
        ):
            return False
    return True


def qa_path(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
        return words[words.index("--qa-dir") + 1]
    except (ValueError, IndexError):
        return ""


def review_calls(directory):
    logs = [
        directory / "agent.log",
        *sorted(directory.glob("final-review-[12].log")),
    ]
    calls, tasks = {}, {}
    index = 0
    for log in logs:
        if not log.exists():
            continue
        for line in log.read_text().splitlines():
            index += 1
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("parent_tool_use_id"):
                continue
            if event.get("type") == "system":
                if (
                    event.get("subtype") == "task_started"
                    and event.get("task_type") == "local_bash"
                ):
                    call = calls.get((log.name, event.get("tool_use_id")))
                    if call:
                        tasks[event.get("task_id")] = call
                        call.background = event.get("is_backgrounded", True)
                        call.end = None
                status = (
                    event.get("patch", {}).get("status")
                    if event.get("subtype") == "task_updated"
                    else event.get("status")
                )
                call = tasks.get(event.get("task_id"))
                if call and status == "completed":
                    if call.end is None:
                        call.end = index
                    end_time = event.get("patch", {}).get("end_time")
                    if call.ended_at is None:
                        call.ended_at = (
                            end_time / 1000
                            if isinstance(end_time, (int, float))
                            else timestamp(event.get("timestamp"))
                        )
            content = event.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in ["tool_use", "server_tool_use"]:
                    if (log.name, block["id"]) in calls:
                        continue
                    name, inputs = block.get("name"), block.get("input", {})
                    command = inputs.get("command", "")
                    if (
                        name == "Bash"
                        and re.search(
                            r"(?:^|[\s;(])(?:sh|bash|node)\s+(?:[^\s;]*/)?render-learning\.(?:sh|mjs)(?:\s|$)",
                            command,
                        )
                        and "--chapters" not in command
                    ):
                        name = "render"
                    if name in ["Read", "advisor", "render"]:
                        calls[(log.name, block["id"])] = Call(
                            name,
                            index,
                            started_at=timestamp(event.get("timestamp")),
                            path=qa_path(command)
                            if name == "render"
                            else inputs.get("file_path", ""),
                        )
                elif block.get("type") in ["tool_result", "advisor_tool_result"]:
                    call = calls.get((log.name, block.get("tool_use_id")))
                    if not call or not successful(block):
                        continue
                    output = block.get("content")
                    if (
                        call.name == "render"
                        and isinstance(output, str)
                        and "running in background" in output.lower()
                    ):
                        call.background = True
                        continue
                    if call.end is not None:
                        if call.name == "render" and call.ended_at is None:
                            call.ended_at = timestamp(event.get("timestamp"))
                        continue
                    if call.name == "Read" and not (
                        isinstance(output, list)
                        and any(
                            part.get("type") == "image"
                            for part in output
                            if isinstance(part, dict)
                        )
                    ):
                        continue
                    call.end = index
                    call.ended_at = timestamp(event.get("timestamp"))
    return list(calls.values())


def inspect_render(
    directory, manifest, calls, latest, previous, until=None, historical=False
):
    report = {
        "passed": False,
        "status": "incomplete",
        "missing_files": [],
        "missing_advisor": True,
        "reviewed_chapters": {},
        "reason": "",
    }
    chapters = manifest.get("chapters", [])
    if (
        not isinstance(chapters, list)
        or not chapters
        or any(
            not isinstance(part, dict) or not part.get("chapter") or not part.get("key")
            for part in chapters
        )
    ):
        report["reason"] = (
            "Final render.json with chapter cache keys is missing; preserve the video and regenerate its QA evidence."
        )
        return report
    ids = [part["chapter"] for part in chapters]
    keys = {part["chapter"]: part["key"] for part in chapters}
    report["chapter_order"] = ids
    report["render_started_at"] = manifest.get("render_started_at")
    previous = (
        previous.get("reviewed_chapters", {})
        if previous.get("chapter_order") == ids
        else {}
    )
    if not isinstance(previous, dict):
        previous = {}
    reviewed = {
        chapter: key for chapter, key in keys.items() if previous.get(chapter) == key
    }
    changed = [chapter for chapter in ids if chapter not in reviewed]
    chapter_files = {
        chapter: sorted(
            path.relative_to(directory).as_posix()
            for path in (directory / "chapters" / chapter / "filmstrip").glob(
                "sheet-*.png"
            )
        )
        for chapter in ids
    }
    root_files = sorted(
        path.relative_to(directory).as_posix()
        for path in (directory / "filmstrip").glob("sheet-*.png")
    )
    if historical:
        chapter_files = manifest["qa"]["chapters"]
        root_files = manifest["qa"]["filmstrip"]
    boundary = latest.end if latest and latest.end is not None else None
    reads = {}
    roots = {str(directory.resolve()).replace("\\", "/").rstrip("/")}
    if latest and latest.path:
        roots.add(latest.path.replace("\\", "/").rstrip("/"))
    for call in calls:
        if (
            call.name != "Read"
            or call.end is None
            or boundary is None
            or call.start <= boundary
            or until is not None
            and call.end >= until
        ):
            continue
        path = call.path.replace("\\", "/")
        for root in roots:
            if path.startswith(root + "/"):
                relative = path[len(root) + 1 :]
                reads[relative] = min(reads.get(relative, call.end), call.end)
    advisors = [
        call
        for call in calls
        if call.name == "advisor"
        and call.end is not None
        and boundary is not None
        and call.start > boundary
        and (until is None or call.end < until)
    ]

    def reviewed_files(files):
        return (
            bool(files)
            and all(
                path in reads and (historical or (directory / path).is_file())
                for path in files
            )
            and any(
                call.start > max(reads[path] for path in files) for call in advisors
            )
        )

    if reviewed_files(root_files):
        reviewed = dict(keys)
        changed = []
    required = set()
    absent = []
    for chapter in changed:
        files = chapter_files[chapter]
        if not files:
            absent.append(f"chapters/{chapter}/filmstrip/")
        needed = list(files)
        at = ids.index(chapter)
        for neighbor, edge in [(at - 1, -1), (at + 1, 0)]:
            if 0 <= neighbor < len(ids) and chapter_files[ids[neighbor]]:
                needed.append(chapter_files[ids[neighbor]][edge])
        required.update(needed)
        if files and reviewed_files(needed):
            reviewed[chapter] = keys[chapter]
    missing = sorted(path for path in required if path not in reads)
    if root_files and (
        absent or len([path for path in root_files if path not in reads]) < len(missing)
    ):
        required = set(root_files)
        missing = sorted(path for path in root_files if path not in reads)
        absent = []
    report["missing_files"] = missing + absent
    report["missing_advisor"] = bool(changed) and not reviewed_files(sorted(required))
    report["reviewed_chapters"] = reviewed
    report["passed"] = (
        not report["missing_files"]
        and not report["missing_advisor"]
        and len(reviewed) == len(keys)
        and boundary is not None
    )
    report["status"] = "complete" if report["passed"] else "incomplete"
    if report["passed"]:
        report["reason"] = (
            "Final filmstrip reads and subsequent lead advisor responses cover all current chapter keys."
        )
    elif boundary is None:
        report["reason"] = (
            "No completed final render is evidenced in the lead tool log."
        )
    else:
        report["reason"] = (
            "Read the missing final filmstrips and chapter joins, then complete a lead advisor review. Retain matching reviewed chapter keys."
        )
    return report


def inspect_final_review(directory):
    directory = Path(directory)
    current = read_json(directory / "render.json")
    saved = read_json(directory / "final-review.json")
    calls = review_calls(directory)
    renders = sorted(
        (call for call in calls if call.name == "render"), key=lambda call: call.start
    )
    history = []
    path = directory / "render-history.jsonl"
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            qa, chapters = entry.get("qa", {}), entry.get("chapters", [])
            if (
                not isinstance(qa, dict)
                or not isinstance(chapters, list)
                or not chapters
            ):
                continue
            inventories = qa.get("chapters", {})
            if not isinstance(inventories, dict) or not all(
                isinstance(part, dict)
                and part.get("chapter") in inventories
                and part.get("key")
                for part in chapters
            ):
                continue
            files = [qa.get("filmstrip"), *inventories.values()]
            if all(
                isinstance(names, list)
                and names
                and all(isinstance(name, str) for name in names)
                for names in files
            ):
                history.append(entry)
    receipt = {}
    for index, render in enumerate(renders):
        final = index == len(renders) - 1
        matches = [
            entry
            for entry in history
            if render.started_at is not None
            and render.ended_at is not None
            and (start := timestamp(entry.get("render_started_at"))) is not None
            and (end := timestamp(entry.get("render_completed_at"))) is not None
            and render.started_at <= start <= end <= render.ended_at
        ]
        if not final and len(matches) != 1:
            receipt = {}
            continue
        manifest = current if final else matches[0]
        if saved.get("render_started_at") == manifest.get("render_started_at") and (
            final or manifest.get("render_started_at")
        ):
            if saved.get("chapter_order") == receipt.get("chapter_order"):
                receipt = {
                    **saved,
                    "reviewed_chapters": {
                        **saved.get("reviewed_chapters", {}),
                        **receipt.get("reviewed_chapters", {}),
                    },
                }
            else:
                receipt = saved
        receipt = inspect_render(
            directory,
            manifest,
            calls,
            render,
            receipt,
            until=None if final else renders[index + 1].start,
            historical=not final,
        )
    return (
        receipt if renders else inspect_render(directory, current, calls, None, saved)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check final visual review evidence without rendering or discarding generated work"
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    report = inspect_final_review(args.directory)
    text = json.dumps(report, indent=2) + "\n"
    temporary = args.directory / "final-review.json.tmp"
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.directory / "final-review.json")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
