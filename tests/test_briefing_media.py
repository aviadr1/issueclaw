import json
from pathlib import Path

import pytest

from issueclaw import briefing_media, design_media, s3_hosting

BASE = "https://bucket.example"
PREFIX = "ci-artifacts/365d/org/mirror"


class Bucket:
    """Records uploads and serves them back by URL, like a public bucket."""

    def __init__(self):
        self.objects = {}

    def put(self, path, bucket, key, public_base, kind=None):
        assert bucket == "ci-bucket" and public_base == BASE
        self.objects[key] = path.read_bytes()
        return f"{public_base}/{key}"


def lesson_dir(out, n, title="Retry ownership", video=True):
    d = out / "learnings" / str(n)
    for rel in ("filmstrip", "qa", "evidence", "source/src"):
        (d / rel).mkdir(parents=True, exist_ok=True)
    (d / "video.mp4").write_bytes(b"mp4")
    (d / "learning.md").write_text("# lesson\n")
    (d / "motion.txt").write_text("holds: none\n")
    (d / "filmstrip/sheet-01.png").write_bytes(b"png1")
    (d / "qa/setup.png").write_bytes(b"png2")
    (d / "agent.log").write_text("transcript with private source")
    (d / "research.md").write_text("private research")
    (d / "evidence/excerpt.py").write_text("private code")
    (d / "source/src/lesson.ts").write_text("export const x = 1;")
    return {
        "n": n,
        "dir": f"learnings/{n}",
        "video": video,
        "title": title,
        "rule": "One owner per retry.",
    }


def test_hosts_only_the_allowlisted_media_under_a_fresh_uuid(tmp_path):
    lessons = [lesson_dir(tmp_path, 1), lesson_dir(tmp_path, 2, video=False)]
    (tmp_path / "learnings.json").write_text(json.dumps(lessons))
    bucket = Bucket()
    hosted = briefing_media.host(
        tmp_path, "ci-bucket", PREFIX, BASE, "123", "2", put=bucket.put
    )
    keys = sorted(bucket.objects)
    root = next(k for k in keys if k.endswith("/index.html")).removesuffix(
        "/index.html"
    )
    assert root.startswith(f"{PREFIX}/daily-learning-briefing/123/2/")
    assert len(root.rsplit("/", 1)[-1]) == 36  # a UUID per run
    assert sorted(k.removeprefix(root + "/") for k in keys) == [
        "index.html",
        "learnings/1/filmstrip/sheet-01.png",
        "learnings/1/learning.md",
        "learnings/1/motion.txt",
        "learnings/1/qa/setup.png",
        "learnings/1/video.mp4",
    ]
    assert hosted["lessons"]["1"]["video"] == f"{BASE}/{root}/learnings/1/video.mp4"
    assert hosted["lessons"]["1"]["page"] == f"{BASE}/{root}/index.html#lesson-1"
    assert "2" not in hosted["lessons"]
    assert json.loads((tmp_path / "hosted-media.json").read_text()) == hosted


def test_symlinked_files_are_never_published(tmp_path):
    lesson = lesson_dir(tmp_path, 1)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not for the bucket")
    (tmp_path / "learnings/1/qa/leak.png").symlink_to(secret)
    (tmp_path / "learnings.json").write_text(json.dumps([lesson]))
    bucket = Bucket()
    briefing_media.host(tmp_path, "ci-bucket", PREFIX, BASE, "1", "1", put=bucket.put)
    assert b"not for the bucket" not in bucket.objects.values()


def test_model_written_text_is_escaped_on_the_public_page(tmp_path):
    lesson = lesson_dir(tmp_path, 1, title='<script>alert("x")</script>')
    (tmp_path / "learnings.json").write_text(json.dumps([lesson]))
    bucket = Bucket()
    briefing_media.host(tmp_path, "ci-bucket", PREFIX, BASE, "1", "1", put=bucket.put)
    index = next(v for k, v in bucket.objects.items() if k.endswith("index.html"))
    assert b"<script>" not in index and b"&lt;script&gt;" in index
    assert b'<video controls preload="metadata" src="learnings/1/video.mp4">' in index


def test_no_published_video_means_no_index(tmp_path):
    (tmp_path / "learnings.json").write_text(
        json.dumps([lesson_dir(tmp_path, 1, video=False)])
    )
    bucket = Bucket()
    hosted = briefing_media.host(
        tmp_path, "ci-bucket", PREFIX, BASE, "1", "1", put=bucket.put
    )
    assert hosted == {"index": None, "lessons": {}} and bucket.objects == {}


def test_put_uploads_with_its_content_type_and_verifies_the_public_bytes(tmp_path):
    clip = tmp_path / "video.mp4"
    clip.write_bytes(b"mp4 bytes")
    calls = []

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

    url = s3_hosting.put(
        clip,
        "ci-bucket",
        "a/b/video.mp4",
        BASE,
        run=lambda args, **kw: calls.append(args),
        get=lambda url, timeout: Response(b"mp4 bytes"),
    )
    assert url == f"{BASE}/a/b/video.mp4"
    assert calls[0][:4] == ["aws", "s3", "cp", str(clip)]
    assert calls[0][4:7] == [
        "s3://ci-bucket/a/b/video.mp4",
        "--content-type",
        "video/mp4",
    ]
    with pytest.raises(ValueError, match="differs"):
        s3_hosting.put(
            clip,
            "ci-bucket",
            "a/b/video.mp4",
            BASE,
            run=lambda args, **kw: None,
            get=lambda url, timeout: Response(b"tampered"),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        s3_hosting.put(clip, "ci-bucket", "k", "http://insecure.example")
    with pytest.raises(ValueError, match="media type"):
        s3_hosting.content_type(tmp_path / "agent.log")


def test_design_media_still_hosts_content_addressed_keys(tmp_path, monkeypatch):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    digest = s3_hosting.digest(b"png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"captures": [{"file": "shot.png", "sha256": digest}]})
    )
    seen = []

    def put(path, bucket, key, public_base, kind=None):
        seen.append((bucket, key, kind))
        return f"{public_base}/{key}"

    monkeypatch.setattr(s3_hosting, "put", put)
    design_media.host_media(manifest, "static", "reports/1", BASE)
    assert seen == [("static", f"reports/1/{digest}.png", "image/png")]
    hosted = json.loads(manifest.read_text())["captures"][0]["hosted_url"]
    assert hosted == f"{BASE}/reports/1/{digest}.png"


def test_cli_requires_the_bucket_settings(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily_briefing",
            "host-media",
            "--config",
            str(config),
            "--out",
            str(tmp_path),
        ],
    )
    from issueclaw import daily_briefing

    with pytest.raises(SystemExit):
        daily_briefing.main()


def briefing_workflow():
    import yaml

    path = Path(__file__).parents[1] / ".github/workflows/daily-learning-briefing.yml"
    return yaml.safe_load(path.read_text())


def test_only_the_data_only_hosting_job_can_mint_upload_credentials():
    workflow = briefing_workflow()
    assert "id-token" not in workflow["permissions"]
    minting = [
        name
        for name, job in workflow["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    ]
    assert minting == ["host-media"]
    job = workflow["jobs"]["host-media"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert job["continue-on-error"] is True
    runs = [step["run"] for step in job["steps"] if "run" in step]
    # one shell step: install the pinned tooling, then host files; nothing downloaded runs
    assert len(runs) == 1
    assert "issueclaw.daily_briefing host-media" in runs[0]
    for word in (
        "claude",
        "npm",
        "render",
        "bash /tmp",
        "sh /tmp",
        "python /tmp/daily",
    ):
        assert word not in runs[0]
    assert [s["uses"].split("@")[0] for s in job["steps"] if "uses" in s] == [
        "actions/checkout",
        "actions/setup-python",
        "astral-sh/setup-uv",
        "actions/download-artifact",
        "aws-actions/configure-aws-credentials",
        "actions/upload-artifact",
    ]


def test_publication_does_not_wait_on_optional_hosting():
    publish = briefing_workflow()["jobs"]["publish"]
    assert "host-media" in publish["needs"]
    assert publish["if"].startswith("${{ !cancelled()")
    assert "needs.generate.result == 'success'" in publish["if"]
    assert "host-media" not in publish["if"]
