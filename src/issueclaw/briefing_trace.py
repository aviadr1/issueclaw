"""Reproducible briefing inputs and video assets, without serializing credentials."""

import hashlib
import json
import shutil
import subprocess


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def model_trace(directory, name, prompt, model, advisor=None, subagents=None):
    (directory / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
    write_json(
        directory / f"{name}.request.json",
        {
            "model": model,
            "advisor": advisor,
            "subagents": subagents,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        },
    )


def preserve_source(videos, directory):
    # Preserve source even on timeout, before the runner checkout disappears.
    for relative in (
        "src/learnings",
        "src/shared",
        "public/learnings",
        "scripts",
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "remotion.config.ts",
    ):
        source = videos / relative
        target = directory / "source" / relative
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def probe(video):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def retime(video, speed):
    """Retiming is atomic: failed conversion never replaces the rendered input."""
    if not 0.5 <= speed <= 1:
        raise ValueError("video playback_speed must be between 0.5 and 1")
    before = probe(video)
    temporary = video.with_name("paced.mp4")
    args = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        f"setpts=(PTS-STARTPTS)/{speed}",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-preset",
        "fast",
    ]
    if any(s["codec_type"] == "audio" for s in before["streams"]):
        args += ["-af", f"atempo={speed}", "-c:a", "aac"]
    args += ["-movflags", "+faststart", str(temporary)]
    with (video.parent / "pacing.log").open("w") as log:
        subprocess.run(
            args, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200
        )
    after = probe(temporary)
    expected = float(before["format"]["duration"]) / speed
    if abs(float(after["format"]["duration"]) - expected) > max(0.3, expected * 0.01):
        raise ValueError("retimed video duration does not match requested speed")
    temporary.replace(video)
    write_json(
        video.parent / "pacing.json",
        {
            "playback_speed": speed,
            "before": before,
            "after": after,
            "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        },
    )


def validate_quality(directory, duration):
    """Enforce the recorded reading budget; visual inspection is still essential."""
    for name in ("questions.md", "research.md", "qa.md"):
        if not (directory / name).read_text().strip():
            raise ValueError(f"missing review trace: {name}")
    scenes = json.loads((directory / "storyboard.json").read_text())
    if not scenes:
        raise ValueError("storyboard has no scenes")
    for index, scene in enumerate(scenes):
        start, end = scene["start_seconds"], scene["end_seconds"]
        fully_visible, hold = (
            scene["fully_visible_seconds"],
            scene["reading_hold_seconds"],
        )
        minimum = max(4, len(scene["visible_text"].split()) / 2.5 + 2)
        if scene.get("interpretation", True):
            minimum += 3
        if index == len(scenes) - 1:
            minimum = max(minimum, 8)
        if not (0 <= start <= fully_visible < end <= duration + 0.1):
            raise ValueError(f"invalid final timing for scene {scene['id']}")
        if hold < minimum or hold > end - fully_visible + 0.1:
            raise ValueError(f"insufficient reading hold for scene {scene['id']}")
        # One image per scene, named by its storyboard ID, enables a human audit.
        if not (directory / "qa" / f"{scene['id']}.png").is_file():
            raise ValueError(f"missing QA frame for scene {scene['id']}")


def write_index(out):
    """Give reviewers a readable entry point, including incomplete attempts."""
    lines = [
        "# Briefing review index",
        "",
        "Start with selection, then watch each clip alongside its questions and QA.",
        "A successful workflow can still contain a text-only or failed video attempt.",
        "",
    ]
    for name in (
        "report.md",
        "selection-audit.json",
        "review-selection.json",
        "learnings.json",
    ):
        if (out / name).exists():
            lines.append(f"- [{name}]({name})")
    for directory in sorted((out / "learnings").glob("*")):
        if not directory.is_dir():
            continue
        prefix = directory.relative_to(out).as_posix()
        lines += ["", f"## Video attempt {directory.name}", ""]
        for name in (
            "topic.json",
            "outcome.json",
            "video.mp4",
            "learning.md",
            "questions.md",
            "research.md",
            "storyboard.json",
            "qa.md",
            "quality.json",
            "pacing.json",
            "agent.request.json",
            "agent.prompt.md",
            "agent.log",
            "error.txt",
            "video-error.txt",
            "pacing-error.txt",
            "render.log",
            "pacing.log",
            "qa",
            "evidence",
            "source",
        ):
            if (directory / name).exists():
                lines.append(f"- [{name}]({prefix}/{name})")
    lines += [
        "",
        "## Reproduction and delivery",
        "",
        "Runner/config JSON files record the run, model CLI version and pinned tooling/video-kit refs.",
        "Generation and revision logs/prompts contain the report's model/tool trace.",
        "The video-kit/source directory also preserves work interrupted before an attempt finished.",
        "After publication, the separate daily-learning-briefing-delivery artifact contains",
        "publication-state.json and pr-video-delivery.json with per-PR delivery receipts.",
        "Artifacts are retained for 90 days; private source material requires repository access.",
        "",
    ]
    (out / "TRACE-INDEX.md").write_text("\n".join(lines), encoding="utf-8")
