"""Replay integration: real git repositories, real apply_webhook, fake Linear/HTTP."""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands import apply_webhook as webhook
from issueclaw import inbox_replay
from issueclaw.inbox_contract import Batch, WorkItem
from tests.test_apply_webhook import _make_issue_api_response


def test_worker_wire_fixture_is_accepted_without_translation():
    batch = Batch.model_validate_json(
        (Path(__file__).parent / "fixtures/inbox-batch.json").read_text()
    )
    assert batch.items[0].key == "test-org/Issue/1"
    assert batch.items[0].generation == 1


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(params=["full", "shallow"])
def repo(tmp_path, request):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    path = tmp_path / "checkout"
    git(tmp_path, "clone", str(remote), str(path))
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("Mirror\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    git(path, "push", "origin", "main")
    if request.param == "shallow":
        # file:// is necessary: local path clones silently ignore --depth.
        (path / "README.md").write_text("Mirror with history\n")
        git(path, "commit", "-am", "second seed commit")
        git(path, "push", "origin", "main")
        path = tmp_path / "shallow"
        git(tmp_path, "clone", "--depth=1", remote.as_uri(), str(path))
        git(path, "config", "user.email", "test@example.com")
        git(path, "config", "user.name", "Test")
        assert git(path, "rev-parse", "--is-shallow-repository") == "true"
    return path, remote


class Inbox:
    def __init__(self, fail_ack=False):
        self.batch = {
            "stream": "test-stream",
            "token": "lease",
            "through": 1,
            "events": [
                {
                    "seq": 1,
                    "payload": {
                        "action": "create",
                        "type": "Issue",
                        "data": {"id": "issue-uuid-1"},
                        "createdAt": "2026-09-13T00:00:00Z",
                    },
                }
            ],
        }
        self.acked = False
        self.fail_ack = fail_ack

    def claim(self):
        return Batch(
            stream="test-stream",
            token="lease",
            items=[
                WorkItem(
                    key="test-org/Issue/issue-uuid-1",
                    generation=1,
                    payload=self.batch["events"][0]["payload"],
                )
            ],
        )

    def ack(self, token, results):
        if self.fail_ack:
            raise OSError("Response lost")
        self.acked = True
        self.results = results


def test_bad_entity_does_not_block_good_entity(repo):
    path, remote = repo
    inbox = Inbox()
    good = inbox.claim().items[0]
    bad = good.model_copy(
        update={
            "key": "test-org/Issue/bad",
            "payload": good.payload.model_copy(update={"data": {"id": "bad"}}),
        }
    )
    inbox.claim = lambda: Batch(stream="test-stream", token="lease", items=[bad, good])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.side_effect = [
        ValueError("bad entity"),
        _make_issue_api_response(),
    ]
    with patch.object(webhook, "LinearClient", return_value=client):
        inbox_replay.drain(inbox, path, "key")
    assert [(r.key, r.success) for r in inbox.results] == [
        (bad.key, False),
        (good.key, True),
    ]
    assert "AI-1-fix-bug.md" in git(remote, "ls-tree", "-r", "main")


def linear():
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.return_value = _make_issue_api_response()
    return patch.object(webhook, "LinearClient", return_value=client)


def test_ack_follows_remote_checkpoint_and_replay_skips_committed_work(repo):
    path, remote = repo
    inbox = Inbox(fail_ack=True)
    with linear(), pytest.raises(OSError):
        inbox_replay.drain(inbox, path, "key")
    checkpoint = json.loads(git(remote, "show", "main:.sync/inbox-checkpoint.json"))
    assert checkpoint["stream"] == "test-stream"
    assert checkpoint["receipts"] == {"test-org/Issue/issue-uuid-1": 1}
    first_commit = git(remote, "rev-parse", "main")
    inbox.fail_ack = False
    # Any attempted re-fetch fails: checkpoint must prevent reapplication.
    with patch.object(webhook, "LinearClient", side_effect=AssertionError("replayed")):
        inbox_replay.drain(inbox, path, "key")
    assert inbox.acked
    assert git(remote, "rev-parse", "main") == first_commit


def test_failed_push_never_acknowledges(repo):
    path, remote = repo
    # Real receiving git rejects the push, not a mock of publish.
    git(remote, "config", "receive.denyNonFastForwards", "true")
    git(path, "remote", "set-url", "--push", "origin", str(path / "absent.git"))
    inbox = Inbox()
    with linear(), pytest.raises(subprocess.CalledProcessError):
        inbox_replay.drain(inbox, path, "key")
    assert not inbox.acked
    assert "inbox-checkpoint" not in git(remote, "ls-tree", "-r", "main")


@pytest.mark.parametrize("failure", ["stream", "unsupported"])
def test_unprocessed_or_wrong_stream_batches_are_not_acknowledged(repo, failure):
    path, remote = repo
    inbox = Inbox()
    if failure == "stream":
        (path / ".sync").mkdir()
        (path / ".sync/inbox-checkpoint.json").write_text('{"stream":"other","seq":1}')
        git(path, "add", ".")
        git(path, "commit", "-m", "other stream")
        git(path, "push", "origin", "main")
    if failure == "unsupported":
        inbox.batch["events"][0]["payload"]["type"] = "Cycle"
    before = git(remote, "rev-parse", "main")
    with (
        patch.object(webhook, "LinearClient", side_effect=RuntimeError("API down")),
        pytest.raises((RuntimeError, ValueError)),
    ):
        inbox_replay.drain(inbox, path, "key")
    assert not inbox.acked
    assert git(remote, "rev-parse", "main") == before


def test_claimed_generation_fetches_parent_once(repo):
    path, _ = repo
    inbox = Inbox()
    client = AsyncMock()
    client.__aenter__.return_value = client
    # A second fetch exhausts the external response stream.
    client.fetch_issue.side_effect = [_make_issue_api_response()]
    with patch.object(webhook, "LinearClient", return_value=client):
        inbox_replay.drain(inbox, path, "key")
    assert inbox.acked
    assert "Fix bug" in (path / "linear/teams/AI/issues/AI-1-fix-bug.md").read_text()


def test_failed_entity_has_no_receipt_and_no_published_changes(repo):
    path, remote = repo
    inbox = Inbox()
    before = git(remote, "rev-parse", "main")
    with patch.object(webhook, "LinearClient", side_effect=RuntimeError("API down")):
        inbox_replay.drain(inbox, path, "key")
    assert inbox.acked
    assert not inbox.results[0].success
    assert git(remote, "rev-parse", "main") == before
    assert not git(path, "status", "--porcelain")


@pytest.mark.parametrize("race", [False, True])
def test_remote_advancement_preserved_or_push_rejected(repo, tmp_path, race):
    path, remote = repo
    peer = tmp_path / "peer"
    git(tmp_path, "clone", remote.as_uri(), str(peer))
    git(peer, "config", "user.email", "peer@example.com")
    git(peer, "config", "user.name", "Peer")

    def advance_remote():
        (peer / "peer.md").write_text("independent update")
        git(peer, "add", ".")
        git(peer, "commit", "-m", "independent update")
        git(peer, "push", "origin", "main")

    inbox = Inbox()
    if race:
        claim = inbox.claim

        def racing_claim():
            advance_remote()
            return claim()

        inbox.claim = racing_claim
        with linear(), pytest.raises(subprocess.CalledProcessError):
            inbox_replay.drain(inbox, path, "key")
        assert not inbox.acked
        assert "inbox-checkpoint" not in git(remote, "ls-tree", "-r", "main")
    else:
        advance_remote()
        with linear():
            inbox_replay.drain(inbox, path, "key")
        assert inbox.acked
    assert git(remote, "show", "main:peer.md") == "independent update"


def test_lost_ack_recovered_from_fresh_shallow_checkout(repo, tmp_path):
    path, remote = repo
    inbox = Inbox(fail_ack=True)
    with linear(), pytest.raises(OSError):
        inbox_replay.drain(inbox, path, "key")
    published = git(remote, "rev-parse", "main")
    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "--depth=1", remote.as_uri(), str(fresh))
    inbox.fail_ack = False
    with patch.object(webhook, "LinearClient", side_effect=AssertionError("replayed")):
        inbox_replay.drain(inbox, fresh, "key")
    assert inbox.acked
    assert git(remote, "rev-parse", "main") == published
