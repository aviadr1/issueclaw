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


def test_readability_gate_rejects_insufficient_final_hold(tmp_path):
    for name in ("questions.md", "research.md", "qa.md"):
        (tmp_path / name).write_text("Reviewed source evidence.")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa/scene.png").write_bytes(b"png")
    scene = {
        "id": "scene",
        "visible_text": "Read this rule.",
        "start_seconds": 0,
        "end_seconds": 10,
        "fully_visible_seconds": 2,
        "reading_hold_seconds": 8,
        "interpretation": False,
    }
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    trace.validate_quality(tmp_path, 10)
    scene["fully_visible_seconds"] = 8
    (tmp_path / "storyboard.json").write_text(json.dumps([scene]))
    with pytest.raises(ValueError, match="hold"):
        trace.validate_quality(tmp_path, 10)


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
    for name in ("questions.md", "research.md", "qa.md"):
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
