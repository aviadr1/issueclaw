"""Recover missing final visual review from tool evidence, retaining reviewed cache keys."""

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Call:
    name: str
    start: int
    end: int | None = None
    path: str = ""
    background: bool = False


def read_json(path):
    try:
        return json.loads(path.read_text())
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
        words = shlex.split(command)
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
                        call.background, call.end = True, None
                status = (
                    event.get("patch", {}).get("status")
                    if event.get("subtype") == "task_updated"
                    else event.get("status")
                )
                call = tasks.get(event.get("task_id"))
                if call and status == "completed" and call.end is None:
                    call.end = index
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
                        and re.search(r"render-learning\.(sh|mjs)(?:\s|$)", command)
                        and "--chapters" not in command
                    ):
                        name = "render"
                    if name in ["Read", "advisor", "render"]:
                        calls[(log.name, block["id"])] = Call(
                            name,
                            index,
                            path=qa_path(command)
                            if name == "render"
                            else inputs.get("file_path", ""),
                        )
                elif block.get("type") in ["tool_result", "advisor_tool_result"]:
                    call = calls.get((log.name, block.get("tool_use_id")))
                    if not call or call.end is not None or not successful(block):
                        continue
                    output = block.get("content")
                    if call.name == "Read" and not (
                        isinstance(output, list)
                        and any(
                            part.get("type") == "image"
                            for part in output
                            if isinstance(part, dict)
                        )
                    ):
                        continue
                    if call.name == "render" and (
                        call.background
                        or isinstance(output, str)
                        and "running in background" in output.lower()
                    ):
                        call.background = True
                        continue
                    call.end = index
    return list(calls.values())


def inspect_final_review(directory):
    directory = Path(directory)
    report = {
        "passed": False,
        "status": "incomplete",
        "missing_files": [],
        "missing_advisor": True,
        "reviewed_chapters": {},
        "reason": "",
    }
    manifest = read_json(directory / "render.json")
    chapters = manifest.get("chapters", [])
    if not chapters or any(
        not part.get("chapter") or not part.get("key") for part in chapters
    ):
        report["reason"] = (
            "Final render.json with chapter cache keys is missing; preserve the video and regenerate its QA evidence."
        )
        return report
    ids = [part["chapter"] for part in chapters]
    keys = {part["chapter"]: part["key"] for part in chapters}
    previous = read_json(directory / "final-review.json").get("reviewed_chapters", {})
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
    calls = review_calls(directory)
    renders = [call for call in calls if call.name == "render"]
    latest = max(renders, key=lambda call: call.start, default=None)
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
    ]

    def reviewed_files(files):
        return (
            bool(files)
            and all(path in reads and (directory / path).is_file() for path in files)
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
