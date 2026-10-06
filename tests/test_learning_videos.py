import json
import subprocess

import pytest

from issueclaw import daily_briefing as daily
from issueclaw import learning_videos as lessons

COMMENT = "https://github.com/org/repo/pull/1#discussion_r1"
OTHER = "https://github.com/org/repo/pull/2#discussion_r2"
LESSON = f"""# LIMIT 1 bounds the answer, not the work

**Problem** A five-second poll asked for one fresh row and still read the whole
backlog of old repairs before it found one, every time it ran.

**Root cause** Its only index held every unfinished row in due order, so the
database had to step past each repair and filter it out ([review]({COMMENT})).

**Fix** A partial index whose condition is the poll's own filter holds only the
rows it can return, so one seek finds the answer.

**Rule** Index the filter you poll, and test it against a large backlog of
rows it must skip.
"""


def briefing(tmp_path, canvas=True):
    """A validated-shape briefing artifact with one review pattern."""
    (tmp_path / "messages").mkdir()
    pattern = {
        "summary": "Polls scan ineligible backlogs",
        "shared_solution": "Index the poll's filter",
        "evidence": [
            {"pr": "org/repo#1", "url": COMMENT},
            {"pr": "org/repo#2", "url": OTHER},
        ],
    }
    files = {
        "window.json": {"delivery_format": "canvas", "timezone": "UTC"}
        if canvas
        else {},
        "delivery.json": {
            "cutoff": "2026-10-05T05:00:00+00:00",
            "files": ["01-toplevel.md"],
            "inventory_files": ["02-inventory.md"],
            "canvas_title": "Backend learning briefing",
        },
        "inventory.json": [],
        "coverage.json": [],
        "review-learning-evidence.json": {
            "review_events": 2,
            "inline_review_comments": 2,
            "comments": [
                {
                    "pr": "org/repo#1",
                    "url": COMMENT,
                    "reviewer": "rae",
                    "body": "LIMIT 1 still scans",
                },
                {
                    "pr": "org/repo#2",
                    "url": "https://github.com/org/repo/pull/2#discussion_r2",
                    "body": "other",
                },
            ],
        },
        "review-learning.json": {
            "review_events": 2,
            "inline_review_comments": 2,
            "inspected_prs": ["org/repo#1", "org/repo#2"],
            "patterns": [pattern],
        },
    }
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value))
    (tmp_path / "coverage.md").write_text("coverage")
    (tmp_path / "messages/01-toplevel.md").write_text("A short TLDR.")
    (tmp_path / "messages/02-inventory.md").write_text(
        "MERGED\n• none", encoding="utf-8"
    )
    (tmp_path / "report.md").write_text(
        "Date and window\n\n## What changed\n\nThings.\n\n"
        f"## What to fix once\n\n{COMMENT} {OTHER}\n"
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Lesson in {learning_dir}, videos in {videos_dir}")
    return prompt


def agent(video=True, body=LESSON, slug="limit-one"):
    def run(prompt, directory, videos, env, instructions=""):
        assert (
            json.loads((directory / "comments.json").read_text())[0]["url"] == COMMENT
        )
        (directory / "learning.md").write_text(body)
        (directory / "learning.json").write_text(
            json.dumps(
                {
                    "slug": slug,
                    "title": "LIMIT 1 bounds the answer, not the work",
                    "rule": "Index the filter you poll.",
                    "sources": [COMMENT],
                }
            )
        )
        if video:
            (directory / "video.mp4").write_bytes(b"\0" * 20_000)

    return run


@pytest.fixture(autouse=True)
def no_ffprobe(monkeypatch):
    real = subprocess.run

    def run(args, **kwargs):
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 1, "", "")
        return real(args, **kwargs)

    monkeypatch.setattr(lessons.subprocess, "run", run)


def test_learn_keeps_a_valid_lesson_and_its_video(tmp_path):
    prompt = briefing(tmp_path)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    assert found == [
        {
            "title": "LIMIT 1 bounds the answer, not the work",
            "rule": "Index the filter you poll.",
            "slug": "limit-one",
            "video": True,
            "n": 1,
            "dir": "learnings/1",
        }
    ]
    # a second run (a retry or revision) reuses the recorded lessons
    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=pytest.fail) == found


@pytest.mark.parametrize(
    "body, slug",
    [
        (LESSON.replace(COMMENT, "https://example.com"), "limit-one"),
        (LESSON.replace("**Root cause**", "Cause"), "limit-one"),
        (LESSON + " word" * 200, "limit-one"),
        (LESSON, "Not A Slug"),
    ],
)
def test_learn_drops_an_unsupported_lesson_without_failing(tmp_path, body, slug):
    prompt = briefing(tmp_path)
    assert (
        lessons.learn(
            tmp_path, prompt, tmp_path, 1, {}, run=agent(body=body, slug=slug)
        )
        == []
    )
    assert (tmp_path / "learnings/1/error.txt").read_text()


def test_a_failed_agent_or_bad_video_never_blocks_the_briefing(tmp_path):
    prompt = briefing(tmp_path)

    def crash(*args):
        raise subprocess.CalledProcessError(1, ["claude", "-p", "long prompt"])

    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=crash) == []
    assert "see agent.log" in (tmp_path / "learnings/1/error.txt").read_text()

    (tmp_path / "learnings.json").unlink()

    def tiny_video(prompt, directory, videos, env, instructions=""):
        agent(video=False)(prompt, directory, videos, env)
        (directory / "video.mp4").write_bytes(b"\0")

    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=tiny_video)
    assert found[0]["video"] is False
    assert (tmp_path / "learnings/1/video-error.txt").read_text()


def test_learn_skips_posted_and_resumed_publications(tmp_path):
    prompt = briefing(tmp_path)
    (tmp_path / "window.json").write_text('{"resume": true}')
    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=pytest.fail) == []


def test_lesson_replaces_the_briefings_learning_where_it_was(tmp_path):
    prompt = briefing(tmp_path)
    lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    messages = daily.validate_output(tmp_path)
    canvas = (tmp_path / "canvas.md").read_text()
    # same place as the briefing's learning: after What changed, not first
    assert canvas.index("## What changed") < canvas.index(
        "## LIMIT 1 bounds the answer, not the work"
    )
    assert "What to fix once" not in canvas
    assert "{{learning-video-1}}" in canvas and "**Root cause**" in canvas
    # the audit still checks the briefing's own citations
    assert OTHER in (tmp_path / "report.md").read_text()
    digest = daily.delivery_digest(tmp_path, messages)
    (tmp_path / "learnings/1/video.mp4").write_bytes(b"\1" * 20_000)
    assert daily.delivery_digest(tmp_path, messages) != digest


def test_lesson_goes_under_the_learning_group_heading(tmp_path):
    prompt = briefing(tmp_path)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    report = (
        "Window\n\n## What changed\n\nThings.\n\n## Learning\n\n"
        f"### Catch slow polls\n\nLong text {COMMENT} {OTHER}\n\n"
        "## CI\n\nGreen checks named.\n"
    )
    out = lessons.replace_learning(tmp_path, report, found)
    assert "## Learning\n\n### LIMIT 1 bounds the answer, not the work" in out
    assert "Catch slow polls" not in out and "Long text" not in out
    assert out.index("**Rule**") < out.index("## CI")


def test_a_learning_the_briefing_never_wrote_is_not_added(tmp_path):
    prompt = briefing(tmp_path)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    report = "Window\n\n## What changed\n\nNo review citations here.\n"
    assert lessons.replace_learning(tmp_path, report, found) == report


def test_placeholders_become_embeds_or_disappear():
    found = [
        {"n": 1, "title": "One", "video": True},
        {"n": 2, "title": "Two", "video": True},
    ]
    content = "a\n\n{{learning-video-1}}\n\nb\n\n{{learning-video-2}}\n\nc"
    filled = lessons.fill_placeholders(
        content, found, {"1": "https://t.slack.com/files/U/F1/v.mp4"}
    )
    assert filled == "a\n\n![One](https://t.slack.com/files/U/F1/v.mp4)\n\nb\n\nc"


class FakeSlack:
    channel = "C1"

    def __init__(self, refuse=None):
        self.refuse = refuse or set()
        self.calls = []
        self.shares = {}

    def start_upload(self, path):
        self.calls.append(("start", path.name))
        if "start" in self.refuse:
            raise daily.SlackRejected("Slack files.getUploadURLExternal: missing_scope")
        return f"F{len(self.calls)}"

    def complete_upload(self, file, title, comment=None, thread=None, share=True):
        self.calls.append(("complete", file, comment, share))
        if share:
            self.shares[file] = "111.1"

    def shared_ts(self, file):
        return self.shares.get(file)

    def file_info(self, file):
        return {"permalink": f"https://t.slack.com/files/U/{file}/video.mp4"}

    def post(self, text, key, thread):
        self.calls.append(("post", text))
        return "222.2"

    def find(self, key):
        return None


def test_tldr_is_shared_as_the_comment_on_the_video(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\0")
    state, slack = {"messages": {}}, FakeSlack()
    daily.publish(
        [("01.md", "TLDR")],
        state,
        "c",
        slack,
        lambda s: None,
        {"01.md": (video, "Lesson")},
    )
    assert ("complete", "F1", "TLDR", True) in slack.calls
    assert not [c for c in slack.calls if c[0] == "post"]
    assert state["messages"]["c/01.md"] == {"ts": "111.1"}


def test_refused_upload_falls_back_to_a_plain_tldr(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\0")
    state, slack = {"messages": {}}, FakeSlack(refuse={"start"})
    daily.publish(
        [("01.md", "TLDR")],
        state,
        "c",
        slack,
        lambda s: None,
        {"01.md": (video, "Lesson")},
    )
    assert ("post", "TLDR") in slack.calls
    assert state["messages"]["c/01.md"] == {"ts": "222.2"}


def test_an_uncertain_video_share_is_recovered_from_the_file(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\0")
    slack = FakeSlack()
    slack.shares["F9"] = "333.3"
    state = {"messages": {"c/01.md": {"intent": True, "file": "F9"}}}
    daily.publish(
        [("01.md", "TLDR")],
        state,
        "c",
        slack,
        lambda s: None,
        {"01.md": (video, "Lesson")},
    )
    assert slack.calls == []
    assert state["messages"]["c/01.md"] == {"ts": "333.3"}
    # a share that never became visible was not made, so it is safely redone
    unshared = {"messages": {"c/01.md": {"intent": True, "file": "F8"}}}
    daily.publish(
        [("01.md", "TLDR")],
        unshared,
        "c",
        slack,
        lambda s: None,
        {"01.md": (video, "Lesson")},
    )
    assert unshared["messages"]["c/01.md"] == {"ts": "111.1"}


def test_canvas_videos_upload_once_and_refusals_stay_skipped(tmp_path):
    prompt = briefing(tmp_path)
    lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    state, saved = {}, []
    slack = FakeSlack()
    links = daily.upload_lesson_videos(tmp_path, state, saved.append, slack)
    assert links == {"1": "https://t.slack.com/files/U/F1/video.mp4"}
    assert ("complete", "F1", None, False) in slack.calls
    assert (
        daily.upload_lesson_videos(
            tmp_path, state, saved.append, FakeSlack(refuse={"start"})
        )
        == links
    )

    refused = {}
    assert (
        daily.upload_lesson_videos(
            tmp_path, refused, saved.append, FakeSlack(refuse={"start"})
        )
        == {}
    )
    assert "missing_scope" in refused["lesson_videos"]["files"]["1"]["skipped"]
    # a later run does not retry, so the Canvas it built stays the same
    assert (
        daily.upload_lesson_videos(tmp_path, refused, saved.append, FakeSlack()) == {}
    )


def test_caller_instructions_reach_the_agent(tmp_path, monkeypatch):
    prompt = briefing(tmp_path)
    seen = []
    monkeypatch.setattr(
        lessons.subprocess, "run", lambda args, **kw: seen.append(args[2])
    )
    lessons.run_agent(prompt, tmp_path, tmp_path, {}, "Use our house style.")
    assert seen[0].endswith("Use our house style.")


def test_rules_go_before_the_closing_invitation_in_title_summaries():
    found = [{"rule": "Index the filter you poll."}]
    text = "**Title**\n\n- Topic\n\nRead today's report"
    assert lessons.with_rules(text, found, before_last_line=True).endswith(
        "- Topic\n\n**Learning:** Index the filter you poll.\nRead today's report"
    )
    assert (
        lessons.with_rules("TLDR", found)
        == "TLDR\n**Learning:** Index the filter you poll."
    )
    assert lessons.with_rules("TLDR", []) == "TLDR"


def test_labels_may_carry_their_colon_inside_the_bold(tmp_path):
    # the label style Opus wrote in the first real CI preview
    prompt = briefing(tmp_path)
    body = LESSON
    for label in ("Problem", "Root cause", "Fix", "Rule"):
        body = body.replace(f"**{label}**", f"**{label}:**")
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent(body=body))
    assert found and found[0]["slug"] == "limit-one"


def test_a_render_the_agent_left_unfinished_is_completed(tmp_path, monkeypatch):
    # the second CI preview: the agent's background render died with its session
    prompt = briefing(tmp_path)
    videos = tmp_path / "kit"
    (videos / "src" / "learnings" / "limit-one").mkdir(parents=True)
    renders = []

    def run(args, **kwargs):
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 1, "", "")
        renders.append(args)
        mp4 = kwargs["cwd"] / "out" / "learnings" / "limit-one.mp4"
        mp4.parent.mkdir(parents=True)
        mp4.write_bytes(b"\0" * 20_000)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(lessons.subprocess, "run", run)
    found = lessons.learn(tmp_path, prompt, videos, 1, {}, run=agent(video=False))
    assert renders == [["sh", "scripts/render-learning.sh", "limit-one"]]
    assert found[0]["video"] is True
