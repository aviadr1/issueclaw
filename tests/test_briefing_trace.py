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
