import json
import subprocess
import sys
from pathlib import Path
from threading import Barrier

import pytest

from issueclaw import daily_briefing as daily
from issueclaw import learning_videos as lessons

COMMENT = "https://github.com/org/repo/pull/1#discussion_r1"
OTHER = "https://github.com/org/repo/pull/2#discussion_r2"
PRIMITIVE = "https://github.com/org/repo/pull/3"
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
REPORT = (
    "Date and window\n\n## What changed\n\nThings.\n\n## Learning\n\n"
    f"### Catch slow polls\n\nLong review write-up {COMMENT} {OTHER}\n\n"
    f"### A new primitive for retries\n\nWhy it works {PRIMITIVE}\n\n"
    "## CI\n\nNamed checks.\n"
)


def briefing(tmp_path, canvas=True, report=REPORT):
    """A validated-shape briefing artifact whose Learning section has two lessons:
    one from a repeated review problem, one about a new primitive."""
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
                {"pr": "org/repo#1", "url": COMMENT, "body": "LIMIT 1 still scans"},
                {"pr": "org/repo#2", "url": OTHER, "body": "other"},
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
    (tmp_path / "report.md").write_text(report, encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Lesson in {learning_dir}, videos in {videos_dir}")
    return prompt


def agent(video=True, body=LESSON, slug="limit-one"):
    def run(prompt, directory, videos, env, instructions=""):
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


def test_learn_keeps_the_lesson_and_its_video(tmp_path):
    prompt = briefing(tmp_path)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    assert found == [
        {
            "title": "LIMIT 1 bounds the answer, not the work",
            "rule": "Index the filter you poll.",
            "slug": "limit-one",
            "sources": [COMMENT],
            "video": True,
            "n": 1,
            "dir": "learnings/1",
            "replaces": "Catch slow polls",
        }
    ]
    # a second run (a retry or revision) reuses the recorded lessons
    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=pytest.fail) == found


@pytest.mark.parametrize("failed", [False, True])
def test_parallel_lessons_own_their_kit_and_preserve_results(tmp_path, failed):
    prompt = briefing(tmp_path)
    kit = tmp_path / "kit"
    registry = Path("src/learnings/registry.ts")
    (kit / registry).parent.mkdir(parents=True)
    (kit / registry).write_text("original")
    both_written = Barrier(2, timeout=5)

    def generate(prompt, directory, videos, env, instructions=""):
        (videos / registry).write_text(directory.name)
        both_written.wait()
        assert (videos / registry).read_text() == directory.name
        if failed and directory.name == "1":
            raise subprocess.CalledProcessError(1, "agent")
        agent()(prompt, directory, videos, env, instructions)

    found = lessons.learn(tmp_path, prompt, kit, 2, {}, run=generate, workers=2)

    assert [row["n"] for row in found] == ([2] if failed else [1, 2])
    assert json.loads((tmp_path / "learnings.json").read_text()) == found
    assert (kit / registry).read_text() == "original"
    for n in (1, 2):
        directory = tmp_path / "learnings" / str(n)
        assert (directory / "source" / registry).read_text() == str(n)
        assert (
            json.loads((directory / "timings.json").read_text())["total_seconds"] >= 0
        )


def test_interrupted_parallel_workspaces_are_preserved(tmp_path):
    kit = tmp_path / ".learning-videos"
    interrupted = tmp_path / ".learning-videos-work-interrupted" / "2"
    source = interrupted / "src/learnings/registry.ts"
    source.parent.mkdir(parents=True)
    source.write_text("unfinished review composition")
    out = tmp_path / "briefing"

    lessons.trace.preserve_video_sources(kit, out)

    assert (
        out / "learnings/2/source/src/learnings/registry.ts"
    ).read_text() == source.read_text()


def test_every_lesson_the_briefing_teaches_is_a_topic_not_only_review_patterns(
    tmp_path,
):
    briefing(tmp_path)
    topics = lessons.select_topics(tmp_path, 5)
    assert [t["heading"] for t in topics] == [
        "Catch slow polls",
        "A new primitive for retries",
    ]
    lessons.write_inputs(tmp_path, tmp_path / "in", topics[1])
    assert PRIMITIVE in (tmp_path / "in/draft.md").read_text()
    # a lesson with no review behind it gets no comments, and that's fine
    assert json.loads((tmp_path / "in/comments.json").read_text()) == []
    lessons.write_inputs(tmp_path, tmp_path / "in1", topics[0])
    cited = json.loads((tmp_path / "in1/comments.json").read_text())
    assert [c["url"] for c in cited] == [COMMENT, OTHER]


def test_a_learning_section_without_subsections_is_one_topic(tmp_path):
    briefing(tmp_path, report="Window\n\n## Learning\n\nOne lesson.\n\n## CI\n\nx\n")
    assert [t["heading"] for t in lessons.select_topics(tmp_path, 5)] == ["Learning"]
    assert lessons.select_topics(tmp_path / "missing", 5) == []


def test_whatever_the_agent_writes_is_used(tmp_path):
    # no format policing: any wording, labels or length is the agent's call
    prompt = briefing(tmp_path)
    found = lessons.learn(
        tmp_path,
        prompt,
        tmp_path,
        1,
        {},
        run=agent(body="# Short\n\nAny text.", slug=""),
    )
    assert found[0]["title"] == "LIMIT 1 bounds the answer, not the work"


def test_a_failed_agent_or_missing_video_never_blocks_the_briefing(tmp_path):
    prompt = briefing(tmp_path)

    def crash(*args):
        raise subprocess.CalledProcessError(1, ["claude", "-p", "long prompt"])

    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=crash) == []
    assert "see agent.log" in (tmp_path / "learnings/1/error.txt").read_text()

    (tmp_path / "learnings.json").unlink()
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent(video=False))
    assert found[0]["video"] is False


def test_learn_skips_posted_and_resumed_publications(tmp_path):
    prompt = briefing(tmp_path)
    (tmp_path / "window.json").write_text('{"resume": true}')
    assert lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=pytest.fail) == []


def test_lesson_replaces_the_briefings_draft_where_it_was(tmp_path):
    prompt = briefing(tmp_path)
    lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    messages = daily.validate_output(tmp_path)
    canvas = (tmp_path / "canvas.md").read_text()
    # in the briefing's own place, under Learning, before CI; the draft is gone
    assert (
        canvas.index("## Learning")
        < canvas.index("### LIMIT 1 bounds the answer, not the work")
        < canvas.index("### A new primitive for retries")
        < canvas.index("## CI")
    )
    assert "Catch slow polls" not in canvas and "Long review write-up" not in canvas
    assert "{{learning-video-1}}" in canvas and "**Root cause**" in canvas
    # the audit still checks the briefing's own citations
    assert OTHER in (tmp_path / "report.md").read_text()
    digest = daily.delivery_digest(tmp_path, messages)
    (tmp_path / "learnings/1/video.mp4").write_bytes(b"\1" * 20_000)
    assert daily.delivery_digest(tmp_path, messages) != digest


def test_a_lone_learning_section_keeps_its_heading_with_the_lesson_under_it(tmp_path):
    report = "Window\n\n## Learning\n\nLong draft.\n\n## CI\n\nNamed checks.\n"
    prompt = briefing(tmp_path, report=report)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    out = lessons.replace_learning(tmp_path, report, found)
    assert "## Learning\n\n### LIMIT 1 bounds the answer, not the work" in out
    assert "Long draft" not in out
    assert out.index("**Rule**") < out.index("## CI")


def test_a_lesson_whose_section_is_gone_is_not_added(tmp_path):
    prompt = briefing(tmp_path)
    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    report = "Window\n\n## What changed\n\nNothing about it here.\n"
    assert lessons.replace_learning(tmp_path, report, found) == report


def test_taught_lessons_are_remembered_with_the_completed_cutoff():
    found = [{"title": "T", "rule": "R", "sources": [COMMENT]}]
    taught = lessons.remember([{"title": "old"}] * 70, found, "2026-10-05")
    assert len(taught) == lessons.TAUGHT_KEPT
    assert taught[-1] == {
        "date": "2026-10-05",
        "title": "T",
        "rule": "R",
        "sources": [COMMENT],
    }

    class Slack:
        def post(self, *args):
            return "1"

        def find(self, key):
            return None

    state = {"messages": {}}
    daily.publish(
        [("01.md", "TLDR")], state, "c", Slack(), lambda s: None, taught=taught
    )
    assert state["taught_lessons"] == taught and state["last_cutoff"] == "c"


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
        lessons.subprocess, "run", lambda args, **kw: seen.append((args, kw))
    )
    lessons.run_agent(prompt, tmp_path, tmp_path, {}, "Use our house style.")
    args, options = seen[0]
    assert args[2].endswith("Use our house style.")
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert args[args.index("--advisor") + 1] == "claude-opus-5-5"
    assert args[args.index("--effort") + 1] == "high"
    assert options["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "haiku"
    request = json.loads((tmp_path / "agent.request.json").read_text())
    assert request["model"] == "claude-sonnet-5-5"
    assert request["advisor"] == "claude-opus-5-5"


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


def test_a_render_the_agent_left_unfinished_is_completed(tmp_path, monkeypatch):
    # the second CI preview: the agent's background render died with its session
    prompt = briefing(tmp_path)
    videos = tmp_path / "kit"
    (videos / "src" / "learnings" / "limit-one").mkdir(parents=True)
    renders = []

    def run(args, **kwargs):
        renders.append(args)
        mp4 = kwargs["cwd"] / "out" / "learnings" / "limit-one.mp4"
        mp4.parent.mkdir(parents=True)
        mp4.write_bytes(b"\0" * 20_000)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(lessons.subprocess, "run", run)
    found = lessons.learn(tmp_path, prompt, videos, 1, {}, run=agent(video=False))
    assert renders == [["sh", "scripts/render-learning.sh", "limit-one"]]
    assert found[0]["video"] is True


def test_review_walkthrough_is_additional_and_pinned_to_collected_head(tmp_path):
    briefing(
        tmp_path,
        report=REPORT
        + "\n## Review walkthrough\n\n### Review the retry system\n\nWhy it needs review.\n",
    )
    row = {
        "repo": "org/repo",
        "number": 3,
        "url": PRIMITIVE,
        "state": "open",
        "headRefOid": "a" * 40,
        "waiting": {"kind": "reviewer"},
    }
    (tmp_path / "inventory.json").write_text(json.dumps([row]))
    (tmp_path / "review-selection.json").write_text(
        json.dumps(
            {
                "pr": "org/repo#3",
                "head_sha": "a" * 40,
                "reason": "Cross-system retry ownership",
                "heading": "Review the retry system",
            }
        )
    )
    selected = lessons.select_topics(tmp_path, 1, review=True)
    assert len(selected) == 2
    assert selected[0]["heading"] == "Catch slow polls"
    assert selected[1]["kind"] == "review"
    assert selected[1]["head_sha"] == "a" * 40
    row["state"] = "merged"
    (tmp_path / "inventory.json").write_text(json.dumps([row]))
    with pytest.raises(ValueError, match="open"):
        lessons.select_topics(tmp_path, 1, review=True)


def test_sources_survive_a_failed_video_agent(tmp_path):
    prompt = briefing(tmp_path)
    videos = tmp_path / "kit"
    source = videos / "src/learnings/example"
    source.mkdir(parents=True)
    (source / "scene.tsx").write_text("const scene = 1;")

    def crash(*args):
        raise subprocess.TimeoutExpired("claude", 1)

    lessons.learn(tmp_path, prompt, videos, 1, {}, run=crash)
    trace = tmp_path / "learnings/1"
    assert (
        trace / "source/src/learnings/example/scene.tsx"
    ).read_text() == "const scene = 1;"
    assert json.loads((trace / "outcome.json").read_text())["status"] == "failed"


def test_reused_preview_preserves_old_video_but_generates_a_replacement(tmp_path):
    prompt = briefing(tmp_path)
    lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent())
    old_manifest = (tmp_path / "learnings.json").read_bytes()
    evidence = (tmp_path / "review-learning-evidence.json").read_bytes()
    lessons.archive_preview_videos(tmp_path, "123")
    assert (
        tmp_path / "previous-videos/123/learnings.json"
    ).read_bytes() == old_manifest
    assert (
        tmp_path / "previous-videos/123/learnings/1/video.mp4"
    ).read_bytes() == b"\0" * 20_000
    assert (tmp_path / "review-learning-evidence.json").read_bytes() == evidence
    revised = "# Context first\n\nA job calls another job; its logs must follow the active job."
    lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=agent(body=revised))
    assert (tmp_path / "learnings/1/learning.md").read_text() == revised


def test_the_shipped_video_prompt_formats_with_every_path(tmp_path, monkeypatch):
    prompt = Path(lessons.__file__).parent / "prompts/learning-video.md"
    seen = []
    monkeypatch.setattr(
        lessons.subprocess, "run", lambda args, **kw: seen.append((args, kw))
    )
    lessons.run_agent(prompt, tmp_path, tmp_path / "kit", {})
    assert len(seen) == 2
    assert "research.md" in seen[0][0][2]
    assert seen[0][1]["cwd"] == tmp_path
    text = seen[1][0][2]
    assert str(tmp_path) in text and str(tmp_path / "kit") in text
    assert "briefing_trace.py" in text
    assert "{learning_dir}" not in text
    assert "{videos_dir}" not in text


def test_lesson_research_receives_the_prepared_team_audience(tmp_path):
    prompt = briefing(tmp_path)
    window = tmp_path / "window.json"
    info = json.loads(window.read_text())
    info.update(title="Frontend learning briefing", audience="Web and mobile engineers")
    window.write_text(json.dumps(info))

    def research(prompt, directory, videos, env, instructions=""):
        topic = json.loads((directory / "topic.json").read_text())
        assert topic["audience"] == "Web and mobile engineers"
        assert topic["briefing_title"] == "Frontend learning briefing"
        agent()(prompt, directory, videos, env, instructions)

    found = lessons.learn(tmp_path, prompt, tmp_path, 1, {}, run=research)
    assert len(found) == 1


def test_learn_command_uses_inherited_video_options_from_prepared_config(
    tmp_path, monkeypatch
):
    prompt = briefing(tmp_path)
    defaults = tmp_path / "defaults.json"
    defaults.write_text(
        json.dumps(
            {
                "learning_videos": {
                    "max": 2,
                    "instructions": "Teach shared client contracts",
                },
            }
        )
    )
    config = tmp_path / "frontend.json"
    config.write_text(
        json.dumps(
            {"defaults": "defaults.json", "repos": ["org/repo"], "channel": "C123"}
        )
    )
    daily.write_json(tmp_path / "briefing-config.json", daily.load_config(config))
    defaults.write_text('{"learning_videos": {"max": 0}}')
    calls = []

    def model(args, **kwargs):
        text = args[2]
        calls.append(text)
        directory = Path(text.split("Lesson in ")[1].split(", videos in ")[0])
        agent(video=False)(prompt, directory, tmp_path, {})

    monkeypatch.setattr(lessons.subprocess, "run", model)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_briefing",
            "learn",
            "--config",
            str(config),
            "--out",
            str(tmp_path),
            "--prompt",
            str(prompt),
            "--videos-dir",
            str(tmp_path),
        ],
    )
    daily.main()
    assert len(lessons.lessons_of(tmp_path)) == 2
    assert len(calls) == 2
    assert all("Teach shared client contracts" in text for text in calls)


def test_video_inputs_reuse_only_records_for_exact_cited_prs(tmp_path):
    briefing(tmp_path)
    records = tmp_path / "pr-records"
    records.mkdir()
    cited = {
        "url": "https://github.com/example/frontend/pull/12",
        "headRefOid": "abc",
        "author": {"login": "author"},
        "body": "Collected evidence",
    }
    unrelated = {
        "url": "https://github.com/example/frontend/pull/123",
        "body": "Unrelated",
    }
    for number, record in [(12, cited), (123, unrelated)]:
        (records / f"example--frontend--{number}.json").write_text(json.dumps(record))
    target = tmp_path / "lesson"
    lessons.write_inputs(tmp_path, target, {"text": cited["url"] + "#discussion_r456"})
    packet = json.loads((target / "collected-prs.json").read_text())
    assert packet["prs"] == [cited]
    assert packet["missing"] == []
    lessons.write_inputs(
        tmp_path, target, {"text": "https://github.com/example/frontend/pull/99"}
    )
    packet = json.loads((target / "collected-prs.json").read_text())
    assert packet["prs"] == []
    assert packet["missing"] == ["https://github.com/example/frontend/pull/99"]


def test_research_failure_preserves_the_handoff_without_starting_authoring(
    tmp_path, monkeypatch
):
    prompt = Path(lessons.__file__).parent / "prompts/learning-video.md"
    seen = []

    def fail(args, **options):
        seen.append(args)
        (tmp_path / "research.md").write_text("Pinned evidence already gathered")
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(lessons.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        lessons.run_agent(prompt, tmp_path, tmp_path / "kit", {})
    assert len(seen) == 1
    assert (tmp_path / "research.md").read_text() == "Pinned evidence already gathered"


def test_trace_key_is_only_passed_in_environment_and_sessions_are_separate(
    tmp_path, monkeypatch
):
    prompt = Path(lessons.__file__).parent / "prompts/learning-video.md"
    plugin = tmp_path / "plugin"
    (plugin / "bundle").mkdir(parents=True)
    (plugin / "bundle/dispatch.js").write_text("")
    seen = []
    monkeypatch.setattr(
        lessons.subprocess, "run", lambda args, **kw: seen.append((args, kw))
    )
    lessons.run_agent(
        prompt,
        tmp_path,
        tmp_path / "kit",
        {
            "LEARNING_TRACE_PLUGIN": str(plugin),
            "CC_LANGSMITH_API_KEY": "private-key",
        },
    )
    sessions = []
    for args, options in seen:
        assert "private-key" not in str(args)
        assert options["env"]["CC_LANGSMITH_API_KEY"] == "private-key"
        assert options["env"]["CC_LANGSMITH_REDACT"] == "true"
        sessions.append(args[args.index("--session-id") + 1])
    assert len(set(sessions)) == 2
    assert "private-key" not in (tmp_path / "research.request.json").read_text()


def test_author_can_delegate_bounded_chapters_without_delegating_review(
    tmp_path, monkeypatch
):
    prompt = Path(lessons.__file__).parent / "prompts/learning-video.md"
    calls = []
    monkeypatch.setattr(
        lessons.subprocess, "run", lambda args, **kw: calls.append((args, kw))
    )
    lessons.run_agent(prompt, tmp_path, tmp_path / "kit", {})
    research, author = [args for args, _ in calls]
    assert "--agents" not in research
    workers = json.loads(author[author.index("--agents") + 1])
    assert workers["chapter-worker"]["model"] == "haiku"
    assert workers["chapter-repair"]["model"] == "sonnet"
    for worker in workers.values():
        assert set(worker["tools"]) == {"Read", "Write", "Edit"}
        assert "Bash" not in worker["tools"]
        assert "advisor" not in worker["tools"]
    assert author[author.index("--advisor") + 1] == lessons.ADVISOR
