import json
from pathlib import PurePosixPath

import pytest

from issueclaw.final_review import inspect_final_review


def tool(name, tool_id, **inputs):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": inputs}
            ]
        },
    }


def result(tool_id, content=None, **extra):
    return {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": content
                    or [{"type": "image", "source": {"data": "PRIVATE_IMAGE"}}],
                    **extra,
                }
            ]
        },
    }


def advisor(tool_id="advisor", **extra):
    return [
        tool("advisor", tool_id),
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "advisor_tool_result",
                        "tool_use_id": tool_id,
                        "content": {
                            "type": "advisor_redacted_result",
                            "encrypted_content": "PRIVATE_ADVICE",
                        },
                        **extra,
                    }
                ]
            },
        },
    ]


def write_log(directory, events, name="agent.log"):
    (directory / name).write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )


@pytest.fixture
def rendered(tmp_path):
    directory = tmp_path / "learnings" / "1"
    directory.mkdir(parents=True)
    (directory / "render.json").write_text(
        json.dumps(
            {
                "chapters": [
                    {"chapter": "setup", "key": "a"},
                    {"chapter": "end", "key": "b"},
                ],
                "qaToReview": [],
            }
        )
    )
    paths = [
        "chapters/setup/filmstrip/sheet-01.png",
        "chapters/end/filmstrip/sheet-01.png",
    ]
    for path in paths:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"image")
    events = [
        tool(
            "Bash",
            "render",
            command=f"sh scripts/render-learning.sh lesson --qa-dir {directory}",
        ),
        result("render", "render complete"),
    ]
    return directory, paths, events


def reads(directory, paths):
    return [
        event
        for index, path in enumerate(paths)
        for event in [
            tool("Read", f"read-{index}", file_path=str(directory / path)),
            result(f"read-{index}"),
        ]
    ]


def test_missing_final_reads_and_advisor_are_reported_despite_claimed_qa(rendered):
    directory, paths, events = rendered
    (directory / "qa.md").write_text("All final filmstrips and advisor review passed.")
    write_log(directory, events)
    report = inspect_final_review(directory)
    assert report["status"] == "incomplete"
    assert set(report["missing_files"]) == set(paths)
    assert report["missing_advisor"] is True
    assert "PRIVATE" not in json.dumps(report)


def test_successful_lead_reads_then_advisor_complete_the_review(rendered):
    directory, paths, events = rendered
    write_log(directory, events + reads(directory, paths) + advisor())
    assert inspect_final_review(directory)["status"] == "complete"


@pytest.mark.parametrize(
    "broken",
    [
        "failed_read",
        "text_read",
        "failed_advisor",
        "advisor_before_reads",
        "worker_reads",
    ],
)
def test_failed_or_out_of_order_evidence_cannot_approve_video(rendered, broken):
    directory, paths, events = rendered
    image_reads = reads(directory, paths)
    advice = advisor()
    if broken == "failed_read":
        image_reads[1]["message"]["content"][0]["is_error"] = True
    elif broken == "text_read":
        image_reads[1]["message"]["content"][0]["content"] = "Error: image unavailable"
    elif broken == "failed_advisor":
        advice[1]["message"]["content"][0]["content"] = {
            "type": "error",
            "error": "private failure",
        }
    elif broken == "worker_reads":
        for event in image_reads:
            event["parent_tool_use_id"] = "worker"
    if broken == "advisor_before_reads":
        events += advice + image_reads
    else:
        events += image_reads + advice
    write_log(directory, events)
    assert inspect_final_review(directory)["status"] == "incomplete"


def test_new_render_invalidates_older_review_and_recovery_logs_can_finish(rendered):
    directory, paths, events = rendered
    write_log(directory, reads(directory, paths) + advisor("old-advisor") + events)
    assert set(inspect_final_review(directory)["missing_files"]) == set(paths)
    write_log(
        directory,
        reads(directory, paths) + advisor("recovery-advisor"),
        "final-review-1.log",
    )
    assert inspect_final_review(directory)["status"] == "complete"


def test_full_final_filmstrip_is_an_alternative_to_chapter_sheets(rendered):
    directory, _, events = rendered
    path = "filmstrip/sheet-01.png"
    (directory / path).parent.mkdir()
    (directory / path).write_bytes(b"image")
    write_log(directory, events + reads(directory, [path]) + advisor())
    assert inspect_final_review(directory)["status"] == "complete"


def test_reads_from_recorded_ci_path_match_downloaded_artifact_location(rendered):
    directory, paths, _ = rendered
    ci = PurePosixPath("/tmp/daily-briefing/learnings/1")
    events = [
        tool(
            "Bash",
            "render",
            command=f"sh scripts/render-learning.sh lesson --qa-dir {ci}",
        ),
        result("render", "render complete"),
    ]
    write_log(directory, events + reads(ci, paths) + advisor())
    assert inspect_final_review(directory)["status"] == "complete"


def test_background_render_requires_completion_before_review(rendered):
    directory, paths, events = rendered
    events[1] = result("render", "Command running in background")
    started = {
        "type": "system",
        "subtype": "task_started",
        "task_type": "local_bash",
        "task_id": "render-job",
        "tool_use_id": "render",
    }
    write_log(directory, events + [started] + reads(directory, paths) + advisor())
    assert inspect_final_review(directory)["status"] == "incomplete"
    completed = {
        "type": "system",
        "subtype": "task_notification",
        "task_id": "render-job",
        "status": "completed",
    }
    write_log(
        directory,
        [completed] + reads(directory, paths) + advisor("final-advisor"),
        "final-review-1.log",
    )
    assert inspect_final_review(directory)["status"] == "complete"


def test_absent_evidence_remains_recoverable_without_fabricating_approval(tmp_path):
    report = inspect_final_review(tmp_path)
    assert report["status"] == "incomplete"
    assert "render.json" in report["reason"]


def test_review_receipts_reuse_unchanged_keys_but_invalidate_changes_and_joins(
    rendered,
):
    directory, paths, events = rendered
    write_log(directory, events + reads(directory, paths) + advisor())
    receipt = inspect_final_review(directory)
    assert receipt["reviewed_chapters"] == {"setup": "a", "end": "b"}
    (directory / "final-review.json").write_text(json.dumps(receipt))
    write_log(directory, events)
    assert inspect_final_review(directory)["passed"] is True
    manifest = json.loads((directory / "render.json").read_text())
    manifest["chapters"][0]["key"] = "changed"
    (directory / "render.json").write_text(json.dumps(manifest))
    report = inspect_final_review(directory)
    assert report["passed"] is False
    assert report["reviewed_chapters"] == {"end": "b"}
    assert set(report["missing_files"]) == set(paths)
    write_log(
        directory,
        reads(directory, [paths[0]]) + advisor("change-advisor"),
        "final-review-1.log",
    )
    report = inspect_final_review(directory)
    assert report["passed"] is False
    assert report["reviewed_chapters"] == {"end": "b"}


def test_partial_review_retains_only_chapters_with_reviewed_boundaries(rendered):
    directory, paths, events = rendered
    extra = directory / "chapters/end/filmstrip/sheet-02.png"
    extra.write_bytes(b"image")
    write_log(directory, events + reads(directory, paths) + advisor())
    report = inspect_final_review(directory)
    assert report["passed"] is False
    assert report["reviewed_chapters"] == {"setup": "a"}
    assert report["missing_files"] == ["chapters/end/filmstrip/sheet-02.png"]


def test_advisor_error_text_does_not_create_a_review_receipt(rendered):
    directory, paths, events = rendered
    advice = advisor()
    advice[1]["message"]["content"][0]["content"] = [
        {"type": "text", "text": "Error: service unavailable"}
    ]
    write_log(directory, events + reads(directory, paths) + advice)
    report = inspect_final_review(directory)
    assert report["passed"] is False
    assert report["reviewed_chapters"] == {}


def test_failed_render_does_not_reuse_prior_filmstrip_reads(rendered):
    directory, paths, events = rendered
    events[1]["message"]["content"][0]["is_error"] = True
    write_log(directory, events + reads(directory, paths) + advisor())
    assert inspect_final_review(directory)["passed"] is False


@pytest.mark.parametrize(
    "manifest", [None, [], {"chapters": None}, {"chapters": [None]}]
)
def test_malformed_render_metadata_requests_recovery_instead_of_losing_work(
    tmp_path, manifest
):
    (tmp_path / "render.json").write_text(json.dumps(manifest))
    (tmp_path / "video.mp4").write_bytes(b"useful render")
    report = inspect_final_review(tmp_path)
    assert report["passed"] is False
    assert "render.json" in report["reason"]
    assert (tmp_path / "video.mp4").read_bytes() == b"useful render"
