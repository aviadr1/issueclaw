import json
import shutil
import subprocess

import pytest

from issueclaw import briefing_trace as trace


@pytest.mark.parametrize("audio", [False, True])
def test_real_video_doubles_duration_and_keeps_streams(tmp_path, audio):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for real media test")
    video = tmp_path / "video.mp4"
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=160x90:r=30:d=1",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    subprocess.run(
        args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True
    )
    trace.retime(video, 0.5)
    result = trace.probe(video)
    assert float(result["format"]["duration"]) == pytest.approx(2, abs=0.1)
    assert any(s["codec_type"] == "audio" for s in result["streams"]) == audio
    assert json.loads((tmp_path / "pacing.json").read_text())["playback_speed"] == 0.5


@pytest.mark.parametrize(
    "text,interpretation,hold",
    [("Read this rule.", False, 4), ("word " * 24, False, 9), ("word " * 24, True, 11)],
)
def test_readability_gate_allows_caption_budget_but_rejects_short_holds(
    tmp_path, text, interpretation, hold
):
    for name in ("questions.md", "research.md", "narrative.md", "qa.md"):
        (tmp_path / name).write_text("Reviewed source evidence.")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/scene.png").write_bytes(b"png")
    scene = {
        "id": "scene",
        "visible_text": text,
        "start_seconds": 0,
        "end_seconds": 2 + hold,
        "fully_visible_seconds": 2,
        "reading_hold_seconds": hold,
        "interpretation": interpretation,
    }
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    trace.validate_quality(tmp_path, 2 + hold)
    scene["reading_hold_seconds"] = hold - 0.5
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    with pytest.raises(ValueError, match="hold"):
        trace.validate_quality(tmp_path, 2 + hold)
    # A claimed hold is insufficient if the scene actually ends too early.
    scene["reading_hold_seconds"] = hold
    scene["fully_visible_seconds"] = 3
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    with pytest.raises(ValueError, match="hold"):
        trace.validate_quality(tmp_path, 2 + hold)


def test_workflow_preserves_traces_without_installed_package(tmp_path):
    """The always-run cleanup must also work outside the reporting virtualenv."""
    import sys
    from pathlib import Path

    import yaml

    root = Path(__file__).parents[1]
    workflow = yaml.safe_load(
        (root / ".github/workflows/daily-learning-briefing.yml").read_text()
    )
    step = next(
        s
        for s in workflow["jobs"]["generate"]["steps"]
        if s.get("name") == "Preserve work-in-progress video source after interruption"
    )
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    out = tmp_path / "artifact"
    out.mkdir()
    script = script.replace("/tmp/daily-briefing", out.as_posix())
    tools = tmp_path / ".briefing-tools/src"
    tools.mkdir(parents=True)
    shutil.copytree(root / "src/issueclaw", tools / "issueclaw")
    source = tmp_path / ".learning-videos/src/learnings/lesson.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("const unfinishedScene = true;")
    subprocess.run([sys.executable, "-S", "-c", script], cwd=tmp_path, check=True)
    assert (
        out / "video-kit/source/src/learnings/lesson.tsx"
    ).read_text() == source.read_text()
    assert (out / "TRACE-INDEX.md").is_file()


def test_storyboard_separators_do_not_consume_reading_time(tmp_path):
    for name in ("questions.md", "research.md", "narrative.md", "qa.md"):
        (tmp_path / name).write_text("Reviewed source evidence.")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/scene.png").write_bytes(b"png")
    scene = {
        "id": "scene",
        "visible_text": " | ".join(["word"] * 12),
        "start_seconds": 0,
        "end_seconds": 10,
        "fully_visible_seconds": 2,
        "reading_hold_seconds": 8,
        "interpretation": False,
    }
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    trace.validate_quality(tmp_path, 10)


def test_reading_windows_allow_diagram_motion_without_hiding_captions(tmp_path):
    for name in ("questions.md", "research.md", "narrative.md", "qa.md"):
        (tmp_path / name).write_text("Reviewed source evidence.")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/scene.png").write_bytes(b"png")
    scene = {
        "id": "scene",
        "visible_text": "Parent job starts a child job. Logs belong to the active job.",
        "start_seconds": 0,
        "end_seconds": 10,
        "reading_windows": [
            {
                "text": "Parent job starts a child job.",
                "fully_visible_seconds": 1,
                "end_seconds": 6,
                "interpretation": False,
            },
            {
                "text": "Logs belong to the active job.",
                "fully_visible_seconds": 5,
                "end_seconds": 10,
                "interpretation": False,
            },
        ],
    }
    path = tmp_path / "storyboard.json"
    path.write_text(json.dumps([scene]))
    trace.validate_quality(tmp_path, 10)
    scene["reading_windows"][1]["end_seconds"] = 7
    path.write_text(json.dumps([scene]))
    with pytest.raises(ValueError, match="reading"):
        trace.validate_quality(tmp_path, 10)
    scene["reading_windows"] = []
    path.write_text(json.dumps([scene]))
    with pytest.raises(ValueError, match="reading"):
        trace.validate_quality(tmp_path, 10)


@pytest.mark.parametrize("moving", [False, True])
def test_motion_gate_measures_the_rendered_clip(tmp_path, moving):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    video = tmp_path / "video.mp4"
    source = (
        "testsrc2=size=160x90:rate=10:duration=6"
        if moving
        else "color=c=blue:s=160x90:r=10:d=6"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    if moving:
        trace.validate_motion(tmp_path)
    else:
        with pytest.raises(ValueError, match="frozen"):
            trace.validate_motion(tmp_path)
    report = json.loads((tmp_path / "motion.json").read_text())
    assert report["passed"] is moving
    assert bool(report["freeze_starts_seconds"]) is (not moving)


def test_trace_index_links_the_kit_filmstrip_and_motion_report(tmp_path):
    attempt = tmp_path / "learnings/1"
    (attempt / "filmstrip").mkdir(parents=True)
    (attempt / "motion.txt").write_text("Holds of 2.5 s or more\n  none\n")
    trace.write_index(tmp_path)
    index = (tmp_path / "TRACE-INDEX.md").read_text()
    assert "- [filmstrip](learnings/1/filmstrip)" in index
    assert "- [motion.txt](learnings/1/motion.txt)" in index
