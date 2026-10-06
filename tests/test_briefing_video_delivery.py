import json

import pytest

from issueclaw import daily_briefing as daily


class Slack:
    channel = "C1"

    def __init__(self):
        self.message = {
            "ts": "1.1",
            "text": "Original TLDR and Canvas link",
            "files": [],
        }
        self.calls = []

    def api(self, method, payload):
        self.calls.append((method, payload))
        if method == "conversations.history":
            return {"messages": [self.message]}
        assert method == "chat.update"
        assert payload["text"] == self.message["text"]
        self.message["files"] = [{"id": file} for file in payload["file_ids"]]
        return {"ok": True, "message": self.message}


def test_attach_existing_file_keeps_tldr_text_and_is_idempotent():
    slack = Slack()
    daily.attach_message_files(slack, "1.1", ["F1"])
    daily.attach_message_files(slack, "1.1", ["F1"])
    updates = [payload for method, payload in slack.calls if method == "chat.update"]
    assert len(updates) == 1
    assert updates[0]["file_ids"] == ["F1"]
    assert slack.message["files"] == [{"id": "F1"}]


def test_attachment_failure_does_not_complete_delivery_and_retry_does_not_repost():
    state = {"messages": {"cutoff/01.md": {"ts": "1.1"}}, "pending": {"run_id": "1"}}
    calls = []

    def finalize():
        calls.append("attach")
        raise daily.SlackRejected("attachment refused")

    with pytest.raises(daily.SlackRejected):
        daily.publish(
            [("01.md", "TLDR")],
            state,
            "cutoff",
            None,
            lambda s: None,
            finalize=finalize,
        )
    assert "last_cutoff" not in state and "pending" in state
    daily.publish(
        [("01.md", "TLDR")],
        state,
        "cutoff",
        None,
        lambda s: None,
        finalize=lambda: calls.append("attached"),
    )
    assert calls == ["attach", "attached"]
    assert state["last_cutoff"] == "cutoff" and "pending" not in state


def test_repair_only_attaches_to_the_latest_completed_briefing(tmp_path):
    cutoff = "2026-10-06T00:34:00+00:00"
    (tmp_path / "delivery.json").write_text(
        json.dumps({"cutoff": cutoff, "files": ["01-toplevel.md"]})
    )
    state = {
        "last_cutoff": cutoff,
        "messages": {cutoff + "/01-toplevel.md": {"ts": "1.1"}},
    }
    slack, saved = Slack(), []
    daily.repair_video_attachment(tmp_path, state, slack, saved.append, ["F1"])
    assert state["last_cutoff"] == cutoff
    assert state["video_repair"]["files"] == ["F1"]
    assert len(saved) == 1
    state["last_cutoff"] = "2026-10-07T05:00:00+00:00"
    with pytest.raises(RuntimeError, match="latest completed"):
        daily.repair_video_attachment(tmp_path, state, slack, saved.append, ["F1"])
