import json
import subprocess

import pytest

from issueclaw import briefing_pr_videos as delivery

REPO = "org/repo"
PR = "https://github.com/org/repo/pull/7"
HEAD = "a" * 40
VIDEO = "https://team.slack.com/files/U/F/video.mp4"
RUN = "https://github.com/org/mirror/actions/runs/123"
HOSTED_VIDEO = "https://bucket.example/ci/learnings/1/video.mp4"
HOSTED_PAGE = "https://bucket.example/ci/index.html#lesson-1"
ASSET = delivery.EMBED + "0000-video"


class GitHub:
    def __init__(self):
        self.comments = []
        self.head = HEAD
        self.patches = 0

    def add(self, body):
        comment = {
            "id": len(self.comments) + 1,
            "body": body,
            "html_url": f"https://github.com/org/repo/issues/7#issuecomment-{len(self.comments) + 1}",
            "user": {"login": "publisher"},
        }
        self.comments.append(comment)
        return comment

    def __call__(self, endpoint, method="GET", data=None, paginate=False):
        if endpoint == "user":
            return {"login": "publisher"}
        if "/pulls/" in endpoint:
            return {"state": "open", "draft": False, "head": {"sha": self.head}}
        if method == "POST":
            assert data is not None
            return self.add(data["body"])
        if method == "PATCH":
            assert data is not None
            comment = next(c for c in self.comments if endpoint.endswith(f"/{c['id']}"))
            comment["body"] = data["body"]
            self.patches += 1
            return comment
        return self.comments


class Commenter:
    """Stands in for `gh pr comment --attach`: uploads, rewrites the reference, posts."""

    def __init__(self, github, mode="ok"):
        self.github = github
        self.mode = mode
        self.calls = []

    def __call__(self, repo, number, body, video, cwd):
        self.calls.append({"repo": repo, "number": number, "video": video, "cwd": cwd})
        assert f"]({video})" in body
        if self.mode == "fails":
            raise subprocess.CalledProcessError(1, ["gh"], stderr="upload refused")
        if self.mode == "posts_unembedded_then_fails":
            self.github.add(body)
            raise subprocess.CalledProcessError(1, ["gh"], stderr="upload refused")
        # like gh 2.99+: the whole `![…](path)` reference becomes the bare asset URL
        comment = self.github.add(body.replace(f"![video]({video})", ASSET))
        if self.mode == "embeds_then_loses_response":
            raise subprocess.TimeoutExpired(["gh"], 600)
        return comment["html_url"]


def artifact(tmp_path, review=False, hosted=True):
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
    if hosted:
        (tmp_path / "hosted-media.json").write_text(
            json.dumps({"lessons": {"1": {"video": HOSTED_VIDEO, "page": HOSTED_PAGE}}})
        )
    return {
        "last_cutoff": "today",
        "lesson_videos": {"cutoff": "today", "files": {"1": {"permalink": VIDEO}}},
    }


def receipt(tmp_path):
    return json.loads((tmp_path / "pr-video-delivery.json").read_text())[0]


def test_video_is_embedded_as_a_player_and_links_the_hosted_review_page(tmp_path):
    state = artifact(tmp_path)
    github = GitHub()
    commenter = Commenter(github)
    delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert commenter.calls == [
        {
            "repo": REPO,
            "number": "7",
            "video": "./learnings/1/video.mp4",
            "cwd": tmp_path,
        }
    ]
    body = github.comments[0]["body"]
    assert f"\n{ASSET}\n" in body and "./learnings" not in body
    assert HOSTED_PAGE in body and VIDEO in body and RUN in body
    assert receipt(tmp_path)["embedded"] is True
    # a rerun finds the comment by its marker and posts nothing new
    delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert len(github.comments) == 1 and len(commenter.calls) == 1


def test_failed_embed_links_the_hosted_video_reports_it_and_never_reposts(tmp_path):
    state = artifact(tmp_path)
    github = GitHub()
    commenter = Commenter(github, mode="fails")
    with pytest.raises(RuntimeError, match="linked, not embedded"):
        delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert len(github.comments) == 1
    assert f"[▶ Watch the video]({HOSTED_VIDEO})" in github.comments[0]["body"]
    assert receipt(tmp_path)["embedded"] is False
    assert "upload refused" not in json.dumps(github.comments)
    delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert len(github.comments) == 1 and len(commenter.calls) == 1


def test_without_hosting_a_failed_embed_falls_back_to_the_slack_post(tmp_path):
    state = artifact(tmp_path, hosted=False)
    github = GitHub()
    with pytest.raises(RuntimeError):
        delivery.attach(
            tmp_path, [REPO], state, RUN, api=github, comment=Commenter(github, "fails")
        )
    body = github.comments[0]["body"]
    assert f"[▶ Watch the video]({VIDEO})" in body and "Review page" not in body


def test_comment_left_with_an_unuploaded_reference_is_repaired_not_duplicated(
    tmp_path,
):
    state = artifact(tmp_path)
    github = GitHub()
    commenter = Commenter(github, mode="posts_unembedded_then_fails")
    with pytest.raises(RuntimeError, match="linked, not embedded"):
        delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert len(github.comments) == 1 and github.patches == 1
    body = github.comments[0]["body"]
    assert "./learnings/1/video.mp4" not in body and HOSTED_VIDEO in body


def test_embed_that_landed_despite_a_lost_response_is_kept(tmp_path):
    state = artifact(tmp_path)
    github = GitHub()
    commenter = Commenter(github, mode="embeds_then_loses_response")
    delivery.attach(tmp_path, [REPO], state, RUN, api=github, comment=commenter)
    assert len(github.comments) == 1 and github.patches == 0
    assert ASSET in github.comments[0]["body"]
    assert receipt(tmp_path)["embedded"] is True


@pytest.mark.parametrize("problem", ["stale_head", "outside_repo", "unpublished"])
def test_does_not_attach_to_unverified_targets(tmp_path, problem):
    state = artifact(tmp_path, review=True)
    github = GitHub()
    commenter = Commenter(github)
    repos = [REPO]
    if problem == "stale_head":
        github.head = "b" * 40
    elif problem == "outside_repo":
        repos = ["other/repo"]
    else:
        state["last_cutoff"] = "yesterday"
    with pytest.raises(RuntimeError):
        delivery.attach(tmp_path, repos, state, RUN, api=github, comment=commenter)
    assert github.comments == [] and commenter.calls == []


def test_gh_comment_attaches_the_video_and_returns_the_comment_url(
    tmp_path, monkeypatch
):
    seen = {}

    def run(args, **kwargs):
        seen.update(args=args, **kwargs)
        return subprocess.CompletedProcess(
            args, 0, stdout="https://github.com/org/repo/pull/7#issuecomment-9\n"
        )

    monkeypatch.setattr(delivery.subprocess, "run", run)
    url = delivery.gh_comment(REPO, "7", "body", "./learnings/1/video.mp4", tmp_path)
    assert url == "https://github.com/org/repo/pull/7#issuecomment-9"
    assert seen["args"][:5] == ["gh", "pr", "comment", "7", "-R"]
    assert seen["args"][-2:] == ["--attach", "./learnings/1/video.mp4"]
    assert seen["input"] == "body" and seen["cwd"] == tmp_path
