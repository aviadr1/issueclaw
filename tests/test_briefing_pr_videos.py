import json

import pytest

from issueclaw import briefing_pr_videos as delivery

REPO = "org/repo"
PR = "https://github.com/org/repo/pull/7"
HEAD = "a" * 40
VIDEO = "https://team.slack.com/files/U/F/video.mp4"


class GitHub:
    def __init__(self):
        self.comments = []
        self.head = HEAD
        self.lose_response = False

    def __call__(self, endpoint, method="GET", data=None, paginate=False):
        if endpoint == "user":
            return {"login": "publisher"}
        if "/pulls/" in endpoint:
            return {"state": "open", "draft": False, "head": {"sha": self.head}}
        if method == "POST":
            assert data is not None
            comment = dict(
                data,
                html_url="https://github.com/org/repo/issues/7#issuecomment-1",
                user={"login": "publisher"},
            )
            self.comments.append(comment)
            if self.lose_response:
                raise TimeoutError("response lost after acceptance")
            return comment
        return self.comments


def artifact(tmp_path, review=False):
    clip = tmp_path / "learnings/1/video.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"video bytes")
    lesson = {
        "n": 1,
        "dir": "learnings/1",
        "video": True,
        "title": "Retry ownership",
        "rule": "One owner per retry.",
        "sources": [PR, PR + "#discussion_r1"],
    }
    if review:
        lesson.update(kind="review", pr="org/repo#7", head_sha=HEAD)
    (tmp_path / "learnings.json").write_text(json.dumps([lesson]))
    (tmp_path / "delivery.json").write_text(json.dumps({"cutoff": "today"}))
    state = {
        "last_cutoff": "today",
        "lesson_videos": {"cutoff": "today", "files": {"1": {"permalink": VIDEO}}},
    }
    return state


def test_comment_links_video_and_recovers_uncertain_write_without_duplicates(tmp_path):
    state = artifact(tmp_path)
    github = GitHub()
    github.lose_response = True
    with pytest.raises(RuntimeError, match="attachment"):
        delivery.attach(
            tmp_path,
            [REPO],
            state,
            "https://github.com/org/mirror/actions/runs/123",
            api=github,
        )
    assert len(github.comments) == 1
    assert VIDEO in github.comments[0]["body"]
    github.lose_response = False
    delivery.attach(
        tmp_path,
        [REPO],
        state,
        "https://github.com/org/mirror/actions/runs/123",
        api=github,
    )
    assert len(github.comments) == 1
    assert (
        json.loads((tmp_path / "pr-video-delivery.json").read_text())[0]["status"]
        == "attached"
    )


@pytest.mark.parametrize("problem", ["stale_head", "outside_repo", "unpublished"])
def test_does_not_attach_to_unverified_targets(tmp_path, problem):
    state = artifact(tmp_path, review=True)
    github = GitHub()
    repos = [REPO]
    if problem == "stale_head":
        github.head = "b" * 40
    elif problem == "outside_repo":
        repos = ["other/repo"]
    else:
        state["last_cutoff"] = "yesterday"
    with pytest.raises(RuntimeError):
        delivery.attach(
            tmp_path,
            repos,
            state,
            "https://github.com/org/mirror/actions/runs/123",
            api=github,
        )
    assert github.comments == []
