"""Daily learning lessons: one root-caused lesson and explainer video per review pattern.

After the briefing is drafted, each review pattern it found (review-learning.json)
can be handed to a separate agent (Claude Opus 5.5, medium effort). The agent
digs into the cited comments and code for the real root cause, writes a short
lesson, and renders a short 3Blue1Brown-style video with the caller's video kit
(a checkout of a repository following promo-videos' ``src/learnings/AGENT.md``).

Everything here is optional and fail-soft. A lesson that fails validation is
dropped, and a missing video leaves the lesson as text, so the briefing never waits
on either. Outputs live in the run artifact under ``learnings/<n>/``; videos are
uploaded to Slack at publish time, not committed anywhere.
"""

import json
import re
import shutil
import subprocess

MODEL = "claude-opus-5-5"
EFFORT = "medium"
AGENT_TIMEOUT = 45 * 60
MAX_VIDEO_BYTES = 60 * 1024 * 1024
PLACEHOLDER = "{{{{learning-video-{n}}}}}"


def placeholder(n):
    return PLACEHOLDER.format(n=n)


def select_patterns(out, limit):
    """The review patterns worth a lesson, in the briefing's own order."""
    audit = json.loads((out / "review-learning.json").read_text())
    return audit.get("patterns", [])[:limit]


def write_inputs(out, directory, pattern):
    """The agent's inputs: the pattern and the exact comment bodies it cites."""
    evidence = json.loads((out / "review-learning-evidence.json").read_text())
    cited = {row.get("url") for row in pattern.get("evidence", [])}
    comments = [c for c in evidence["comments"] if c["url"] in cited]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pattern.json").write_text(json.dumps(pattern, indent=2) + "\n")
    (directory / "comments.json").write_text(json.dumps(comments, indent=2) + "\n")
    return cited


def run_agent(prompt, directory, videos, env, instructions=""):
    text = prompt.read_text().format(
        learning_dir=directory.resolve(), videos_dir=videos.resolve()
    )
    if instructions:
        text += "\n\nThe caller's instructions for this lesson and its video:\n"
        text += instructions
    with (directory / "agent.log").open("w") as log:
        subprocess.run(
            [
                shutil.which("claude") or "claude",
                "-p",
                text,
                "--dangerously-skip-permissions",
                "--model",
                MODEL,
                "--effort",
                EFFORT,
                "--output-format",
                "text",
            ],
            cwd=videos,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=AGENT_TIMEOUT,
        )


def validate_lesson(directory, cited):
    """A lesson is short, structured, cites the review it came from, and names one rule."""
    meta = json.loads((directory / "learning.json").read_text())
    body = (directory / "learning.md").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", meta.get("slug", "")):
        raise ValueError("learning.json slug must be lowercase and hyphenated")
    title, rule = meta.get("title", "").strip(), meta.get("rule", "").strip()
    if not title or not rule or len(rule.split()) > 30:
        raise ValueError("learning.json needs a title and a rule of at most 30 words")
    if not body.startswith("# "):
        raise ValueError("learning.md must start with its '# ' title")
    words = len(body.split("\n", 1)[-1].split())
    if not 50 <= words <= 200:
        raise ValueError(f"learning.md body has {words} words; keep it to 50-200")
    for label in ("**Problem**", "**Root cause**", "**Fix**", "**Rule**"):
        if label not in body:
            raise ValueError(f"learning.md is missing {label}")
    if not any(url in body for url in cited):
        raise ValueError("learning.md must link the review comment it came from")
    return {"title": title, "rule": rule, "slug": meta["slug"]}


def validate_video(path):
    size = path.stat().st_size
    if not 10_000 < size <= MAX_VIDEO_BYTES:
        raise ValueError(f"video.mp4 is {size} bytes")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        seconds = float(probe.stdout.strip())
        if not 10 <= seconds <= 75:
            raise ValueError(f"video.mp4 is {seconds:.0f} s; keep it to 10-75 s")


def learn(out, prompt, videos, limit, env, instructions="", run=run_agent):
    """Prepare up to `limit` lessons; record what succeeded in learnings.json."""
    info = json.loads((out / "window.json").read_text())
    if info.get("already_posted") or info.get("resume"):
        return []
    manifest = out / "learnings.json"
    if manifest.exists():
        return json.loads(manifest.read_text())
    lessons = []
    for n, pattern in enumerate(select_patterns(out, limit), 1):
        directory = out / "learnings" / str(n)
        try:
            cited = write_inputs(out, directory, pattern)
            run(prompt, directory, videos, env, instructions)
            lesson = validate_lesson(directory, cited)
        except subprocess.CalledProcessError as error:
            note = f"agent exited with {error.returncode}; see agent.log"
            (directory / "error.txt").write_text(note + "\n")
            continue
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            note = f"{type(error).__name__}: {str(error)[:500]}"
            (directory / "error.txt").write_text(note + "\n")
            continue
        video = directory / "video.mp4"
        lesson["video"] = False
        if video.exists():
            try:
                validate_video(video)
                lesson["video"] = True
            except (OSError, ValueError) as error:
                (directory / "video-error.txt").write_text(f"{error}\n")
        lesson["n"] = n
        lesson["dir"] = f"learnings/{n}"
        lessons.append(lesson)
    manifest.write_text(json.dumps(lessons, indent=2) + "\n")
    return lessons


def lessons_of(out):
    path = out / "learnings.json"
    return json.loads(path.read_text()) if path.exists() else []


HEADING = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
GROUP_HEADINGS = {"learning"}


def sections(lines):
    """(start, end, level, text) of every heading's section, end exclusive."""
    found = []
    heads = [(i, m) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    for k, (i, m) in enumerate(heads):
        level = len(m[1])
        end = next(
            (j for j, n in heads[k + 1 :] if len(n[1]) <= level),
            len(lines),
        )
        found.append((i, end, level, m[2]))
    return found


def replace_learning(out, report, lessons):
    """Put each lesson where the briefing wrote that learning, replacing its text.

    The briefing's learning is the smallest section citing the pattern's review
    comments. Its heading keeps its level and takes the lesson's title, unless it
    is the "Learning" group heading itself, which stays with the lesson under it.
    A learning the report never wrote up is not added.
    """
    for lesson in lessons:
        pattern = json.loads((out / lesson["dir"] / "pattern.json").read_text())
        urls = [row["url"] for row in pattern.get("evidence", [])]
        lines = report.split("\n")
        citing = [
            s
            for s in sections(lines)
            if urls and all(url in "\n".join(lines[s[0] : s[1]]) for url in urls)
        ]
        if not citing:
            continue
        start, end, level, text = min(citing, key=lambda s: s[1] - s[0])
        body = (out / lesson["dir"] / "learning.md").read_text(encoding="utf-8")
        body = body.strip().split("\n", 1)[-1].strip()
        video = placeholder(lesson["n"]) + "\n\n" if lesson["video"] else ""
        if text.strip().casefold() in GROUP_HEADINGS:
            head = [lines[start], "", "#" * (level + 1) + " " + lesson["title"]]
        else:
            head = ["#" * level + " " + lesson["title"]]
        lesson_lines = head + [""] + (video + body).split("\n") + [""]
        report = "\n".join(lines[:start] + lesson_lines + lines[end:])
    return report


def fill_placeholders(content, lessons, permalinks):
    """Embed each uploaded video; drop the placeholder of one that wasn't uploaded."""
    for lesson in lessons:
        link = permalinks.get(str(lesson["n"]))
        embed = f"![{lesson['title']}]({link})" if link else ""
        content = content.replace(
            placeholder(lesson["n"]) + "\n\n", embed + "\n\n" if embed else ""
        )
    return content


def tldr_line(lessons):
    return "".join(f"\n**Learning:** {lesson['rule']}" for lesson in lessons)


def with_rules(text, lessons, *, before_last_line=False):
    """Add each lesson's rule to the Slack message, before its closing line if asked."""
    rules = tldr_line(lessons)
    if not rules:
        return text
    body, newline, last = text.rpartition("\n")
    if before_last_line and newline:
        return body + rules + "\n" + last
    return text + rules
