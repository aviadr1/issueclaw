"""Host each briefing video's review media on the public-by-URL CI artifact bucket.

Runs in its own job after generation and treats the downloaded run artifact as
data. Only an allowlist leaves it: per video, the MP4, its filmstrip, QA stills,
motion report and lesson text. The agent's transcript, prompts, research, evidence
and captured source stay in the private run artifact. Uploads go under a fresh
UUID (hard to guess, but anyone with a URL can share it), and an index page plus
hosted-media.json record where everything landed for the publish job.
"""

import html
import uuid
from pathlib import Path

from issueclaw import briefing_trace as trace
from issueclaw import learning_videos, s3_hosting

MAX_BYTES = 100 * 1024 * 1024
WORKFLOW = "daily-learning-briefing"


def selected(out: Path, lesson: dict) -> list[Path]:
    """The allowlisted files of one video, inside its own directory and not links."""
    root = (out / lesson["dir"]).resolve()
    candidates = [
        root / "video.mp4",
        root / "learning.md",
        root / "motion.txt",
        *sorted((root / "filmstrip").glob("*.png")),
        *sorted((root / "qa").glob("*.png")),
    ]
    return [
        path
        for path in candidates
        if path.is_file()
        and not path.is_symlink()
        and root in path.resolve().parents
        and path.stat().st_size <= MAX_BYTES
    ]


def page(lessons: list[dict]) -> str:
    """A self-contained review page; every model-written string is escaped."""
    sections = []
    for lesson in lessons:
        n = lesson["n"]
        files = lesson["files"]
        kind = "Review walkthrough" if lesson.get("kind") == "review" else "Lesson"
        stills = "".join(
            f'<a href="{html.escape(rel)}"><img src="{html.escape(rel)}" alt="{html.escape(rel.rsplit("/", 1)[-1])}"></a>'
            for rel in files
            if rel.endswith(".png")
        )
        texts = " · ".join(
            f'<a href="{html.escape(rel)}">{html.escape(rel.rsplit("/", 1)[-1])}</a>'
            for rel in files
            if rel.endswith((".md", ".txt"))
        )
        sections.append(
            f'<section id="lesson-{n}"><h2>{kind}: {html.escape(lesson["title"])}</h2>'
            f"<p>{html.escape(lesson['rule'])}</p>"
            f'<video controls preload="metadata" src="{html.escape(lesson["video"])}"></video>'
            f"<p>{texts}</p><div class=stills>{stills}</div></section>"
        )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<title>Briefing videos</title><style>"
        "body{background:#0f0f12;color:#ececec;font:16px/1.5 system-ui,sans-serif;"
        "max-width:1100px;margin:0 auto;padding:16px}a{color:#58c4dd}"
        "video{width:100%;background:#000}.stills{display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px}"
        ".stills img{width:100%}</style></head><body><h1>Briefing videos</h1>"
        + "".join(sections)
        + "</body></html>"
    )


def host(out, bucket, prefix, public_base, run_id, attempt, put=s3_hosting.put):
    """Upload every published video's media and write hosted-media.json."""
    out = Path(out).resolve()
    root = f"{prefix.strip('/')}/{WORKFLOW}/{run_id}/{attempt}/{uuid.uuid4()}"
    hosted = {"index": None, "lessons": {}}
    pages = []
    for lesson in learning_videos.lessons_of(out):
        if not lesson.get("video"):
            continue
        files = {}
        for path in selected(out, lesson):
            rel = path.relative_to(out).as_posix()
            files[rel] = put(path, bucket, f"{root}/{rel}", public_base)
        video = f"{lesson['dir']}/video.mp4"
        if video not in files:
            continue
        hosted["lessons"][str(lesson["n"])] = {
            "video": files[video],
            "files": sorted(files.values()),
        }
        pages.append(dict(lesson, video=video, files=sorted(files)))
    if pages:
        index = out / "hosted-media.html"
        index.write_text(page(pages), encoding="utf-8")
        hosted["index"] = put(index, bucket, f"{root}/index.html", public_base)
        for n, entry in hosted["lessons"].items():
            entry["page"] = f"{hosted['index']}#lesson-{n}"
    trace.write_json(out / "hosted-media.json", hosted)
    return hosted
