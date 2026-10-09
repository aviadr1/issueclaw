"""Daily learning lessons: each lesson the briefing teaches, deepened and explained on video.

After the briefing is drafted, each lesson in its Learning section can be handed to
a separate agent (Sonnet 5.5, medium effort, with an Opus advisor). A lesson can be any kind of
knowledge worth sharing: a repeated review problem, a new system or primitive, a
CI fix, an algorithm, a measured optimisation, a restructuring. The agent digs into
the cited PRs, comments and code for what really happened and why, writes a short
lesson that replaces the briefing's draft in place, and renders a short explainer
video with the caller's video kit (a checkout of a repository following
promo-videos' ``src/learnings/AGENT.md``).

Everything here is optional and fail-soft. A lesson the agent didn't write is
dropped, and a missing video leaves the lesson as text, so the briefing never waits
on either. Outputs live in the run artifact under ``learnings/<n>/``; videos are
uploaded to Slack at publish time, not committed anywhere.
"""

import json
import re
import shutil
import subprocess

from issueclaw import briefing_trace as trace

MODEL = "claude-sonnet-5-5"
ADVISOR = "claude-opus-5-5"
EFFORT = "medium"
AGENT_TIMEOUT = 45 * 60
RENDER_TIMEOUT = 20 * 60
PLACEHOLDER = "{{{{learning-video-{n}}}}}"
HEADING = re.compile(r"^(#{2,6})\s+(.+?)\s*$")


def placeholder(n):
    return PLACEHOLDER.format(n=n)


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


def is_learning_heading(text):
    text = text.strip().casefold()
    return text == "learning" or text.startswith("what to fix once")


def select_topics(out, limit, review=False):
    """The lessons the briefing wrote, in its order: each subsection of its
    Learning section, or the section itself when it has none."""
    path = out / "report.md"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    found = sections(lines)
    group = next((s for s in found if is_learning_heading(s[3])), None)
    topics = []
    if group is not None:
        start, end, level, _ = group
        children = [s for s in found if start < s[0] < end and s[2] == level + 1]
        topics = [
            {"heading": s[3], "text": "\n".join(lines[s[0] : s[1]]).strip()}
            for s in (children or [group])
        ][:limit]
    if review:
        choice = json.loads((out / "review-selection.json").read_text())
        if choice.get("pr") is None:
            if not choice.get("reason"):
                raise ValueError("review selection needs a no-candidate reason")
            return topics
        inventory = json.loads((out / "inventory.json").read_text())
        row = next(
            (r for r in inventory if f"{r['repo']}#{r['number']}" == choice["pr"]), None
        )
        if row is None or row["state"] != "open":
            raise ValueError("review walkthrough must select an open non-draft PR")
        if (
            row.get("reviewDecision") == "APPROVED"
            or row.get("waiting", {}).get("kind") != "reviewer"
        ):
            raise ValueError("review walkthrough must be waiting for a reviewer")
        if not row.get("headRefOid") or row["headRefOid"] != choice.get("head_sha"):
            raise ValueError("review walkthrough head differs from collected evidence")
        review_group = next(
            (s for s in found if s[3] == "Review walkthrough" and s[2] == 2), None
        )
        section = next((s for s in found if s[3] == choice.get("heading")), None)
        if (
            section is None
            or review_group is None
            or not (review_group[0] < section[0] < review_group[1])
            or section[2] != 3
        ):
            raise ValueError("review walkthrough heading missing from report")
        topics.append(
            {
                "heading": section[3],
                "text": "\n".join(lines[section[0] : section[1]]).strip(),
                "kind": "review",
                "pr": choice["pr"],
                "head_sha": choice["head_sha"],
                "url": row["url"],
            }
        )
    return topics


def write_inputs(out, directory, topic):
    """The agent's inputs: the briefing's draft and the review comments it cites."""
    evidence = json.loads((out / "review-learning-evidence.json").read_text())
    comments = [c for c in evidence["comments"] if c["url"] in topic["text"]]
    directory.mkdir(parents=True, exist_ok=True)
    trace.write_json(directory / "topic.json", topic)
    (directory / "draft.md").write_text(topic["text"] + "\n", encoding="utf-8")
    (directory / "comments.json").write_text(json.dumps(comments, indent=2) + "\n")


def run_agent(prompt, directory, videos, env, instructions=""):
    text = prompt.read_text().format(
        learning_dir=directory.resolve(),
        videos_dir=videos.resolve(),
        quality_validator=trace.__file__,
    )
    if instructions:
        text += "\n\nThe caller's instructions for this lesson and its video:\n"
        text += instructions
    trace.model_trace(
        directory, "agent", text, MODEL, advisor=ADVISOR, subagents="haiku"
    )
    with (directory / "agent.log").open("w") as log:
        subprocess.run(
            [
                shutil.which("claude") or "claude",
                "-p",
                text,
                "--dangerously-skip-permissions",
                "--model",
                MODEL,
                "--advisor",
                ADVISOR,
                "--effort",
                EFFORT,
                "--output-format",
                "stream-json",
                "--verbose",
            ],
            cwd=videos,
            env=dict(env, CLAUDE_CODE_SUBAGENT_MODEL="haiku"),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=AGENT_TIMEOUT,
        )


def read_lesson(directory):
    """The lesson's title, rule and sources, for the Canvas, Slack and memory."""
    meta = json.loads((directory / "learning.json").read_text())
    body = (directory / "learning.md").read_text(encoding="utf-8").strip()
    title, rule = meta.get("title", "").strip(), meta.get("rule", "").strip()
    if not body or not title or not rule:
        raise ValueError("the agent wrote no lesson")
    sources = [url for url in meta.get("sources", []) if isinstance(url, str)]
    return {
        "title": title,
        "rule": rule,
        "slug": meta.get("slug", ""),
        "sources": sources,
    }


def finish_render(videos, slug, video, env):
    """Render the agent's composition if it left without a video (e.g. a killed render)."""
    if not (videos / "src" / "learnings" / slug).is_dir():
        return
    with (video.parent / "render.log").open("w") as log:
        try:
            subprocess.run(
                ["sh", "scripts/render-learning.sh", slug],
                cwd=videos,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=RENDER_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return
    rendered = videos / "out" / "learnings" / f"{slug}.mp4"
    if rendered.exists():
        shutil.copyfile(rendered, video)


def learn(
    out,
    prompt,
    videos,
    limit,
    env,
    instructions="",
    run=run_agent,
    *,
    review=False,
    playback_speed=1,
    quality_checks=False,
):
    """Prepare up to `limit` lessons; record what succeeded in learnings.json."""
    info = json.loads((out / "window.json").read_text())
    if info.get("already_posted") or info.get("resume"):
        return []
    manifest = out / "learnings.json"
    if manifest.exists():
        return json.loads(manifest.read_text())
    lessons = []
    for n, topic in enumerate(select_topics(out, limit, review=review), 1):
        directory = out / "learnings" / str(n)
        directory.mkdir(parents=True, exist_ok=True)
        status = "failed"
        try:
            write_inputs(out, directory, topic)
            run(prompt, directory, videos, env, instructions)
            lesson = read_lesson(directory)
            status = "written"
        except subprocess.CalledProcessError as error:
            note = f"agent exited with {error.returncode}; see agent.log"
            (directory / "error.txt").write_text(note + "\n")
            continue
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            note = f"{type(error).__name__}: {str(error)[:500]}"
            (directory / "error.txt").write_text(note + "\n")
            continue
        finally:
            trace.preserve_source(videos, directory)
            trace.write_json(directory / "outcome.json", {"status": status})
        video = directory / "video.mp4"
        if not video.exists() and lesson["slug"]:
            finish_render(videos, lesson["slug"], video, env)
        lesson["video"] = video.exists() and video.stat().st_size > 0
        if lesson["video"] and playback_speed != 1:
            try:
                trace.retime(video, playback_speed)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                lesson["video"] = False
                (directory / "pacing-error.txt").write_text(
                    f"{type(error).__name__}: pacing failed; see pacing.log\n"
                )
        if lesson["video"] and quality_checks:
            try:
                duration = float(trace.probe(video)["format"]["duration"])
                trace.validate_quality(directory, duration)
                trace.validate_motion(directory)
                trace.write_json(
                    directory / "quality.json", {"passed": True, "duration": duration}
                )
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                lesson["video"] = False
                trace.write_json(
                    directory / "quality.json",
                    {"passed": False, "error": str(error)[:500]},
                )
        if topic.get("kind") == "review":
            lesson.update(kind="review", pr=topic["pr"], head_sha=topic["head_sha"])
            if topic["url"] not in lesson["sources"]:
                lesson["sources"].append(topic["url"])
        trace.write_json(
            directory / "outcome.json",
            {"status": "video" if lesson["video"] else "text_only"},
        )
        lesson["n"] = n
        lesson["dir"] = f"learnings/{n}"
        lesson["replaces"] = topic["heading"]
        lessons.append(lesson)
        manifest.write_text(json.dumps(lessons, indent=2) + "\n")
    manifest.write_text(json.dumps(lessons, indent=2) + "\n")
    return lessons


def lessons_of(out):
    path = out / "learnings.json"
    return json.loads(path.read_text()) if path.exists() else []


def replace_learning(out, report, lessons):
    """Put each lesson where the briefing wrote it, replacing the briefing's draft.

    The draft is the section whose heading the lesson came from. Its heading keeps
    its level and takes the lesson's title, unless it is the Learning group heading
    itself, which stays with the lesson under it.
    """
    for lesson in lessons:
        lines = report.split("\n")
        match = [s for s in sections(lines) if s[3] == lesson.get("replaces")]
        if not match:
            continue
        start, end, level, text = match[0]
        body = (out / lesson["dir"] / "learning.md").read_text(encoding="utf-8")
        body = body.strip().split("\n", 1)[-1].strip()
        video = placeholder(lesson["n"]) + "\n\n" if lesson["video"] else ""
        if is_learning_heading(text):
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
    return "".join(
        f"\n**{'Review walkthrough' if lesson.get('kind') == 'review' else 'Learning'}:** {lesson['rule']}"
        for lesson in lessons
    )


def with_rules(text, lessons, *, before_last_line=False):
    """Add each lesson's rule to the Slack message, before its closing line if asked."""
    rules = tldr_line(lessons)
    if not rules:
        return text
    body, newline, last = text.rpartition("\n")
    if before_last_line and newline:
        return body + rules + "\n" + last
    return text + rules


TAUGHT_KEPT = 60


def remember(taught, lessons, date):
    """The lessons already taught, newest last, so the briefing doesn't repeat one."""
    taught = list(taught or [])
    for lesson in lessons:
        if lesson.get("kind") == "review":
            continue
        taught.append(
            {
                "date": date,
                "title": lesson["title"],
                "rule": lesson["rule"],
                "sources": lesson.get("sources", []),
            }
        )
    return taught[-TAUGHT_KEPT:]
