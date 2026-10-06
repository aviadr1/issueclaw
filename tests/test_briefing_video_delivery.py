import json

import httpx
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
        if "text" in payload:
            assert payload["text"] == self.message["text"]
            self.message["blocks"] = payload.get("blocks", [])
        if "markdown_text" in payload:
            self.message["blocks"] = [
                {
                    "type": "rich_text",
                    "elements": [
                        {"type": "rich_text_list", "style": "bullet", "indent": 0},
                        {"type": "rich_text_list", "style": "bullet", "indent": 1},
                    ],
                }
            ]
        if "file_ids" in payload:
            self.message["files"] = [{"id": file} for file in payload["file_ids"]]
        return {"ok": True, "message": self.message}


def test_publisher_submits_markdown_for_native_nested_lists():
    markdown = (
        "**Briefing**\n\n- CI\n  - Tests passed\n\n[Canvas](https://slack.com/docs/F1)"
    )
    payloads = []

    def receive(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "1.1"})

    slack = daily.Slack("C1", "test-token")
    slack.client.close()
    with httpx.Client(
        base_url="https://slack.com/api/", transport=httpx.MockTransport(receive)
    ) as client:
        slack.client = client
        assert slack.post(markdown, "cutoff/01.md", None) == "1.1"
    payload = payloads[0]
    assert payload["markdown_text"] == markdown
    assert "text" not in payload and "blocks" not in payload
    assert payload["metadata"]["event_payload"]["key"] == "cutoff/01.md"


def test_attaching_video_keeps_native_list_blocks():
    slack = Slack()
    blocks = [
        {
            "type": "rich_text",
            "elements": [{"type": "rich_text_list", "style": "bullet", "indent": 1}],
        }
    ]
    slack.message["blocks"] = blocks
    daily.attach_message_files(slack, "1.1", ["F1"])
    assert slack.message["blocks"] == blocks


def test_formatting_existing_message_keeps_video_and_rejects_changed_text():
    slack = Slack()
    markdown = (
        "**Briefing**\n\n- CI\n  - Tests passed\n\n[Canvas](https://slack.com/docs/F2)"
    )
    slack.message["text"] = daily.mrkdwn(markdown)
    slack.message["files"] = [{"id": "F1"}]
    daily.attach_message_files(slack, "1.1", ["F1"], markdown=markdown)
    update = [payload for method, payload in slack.calls if method == "chat.update"][0]
    assert update["markdown_text"] == markdown
    assert "text" not in update and "blocks" not in update
    assert slack.message["files"] == [{"id": "F1"}]
    assert slack.message["blocks"][0]["elements"][0]["type"] == "rich_text_list"
    with pytest.raises(RuntimeError, match="text differs"):
        daily.attach_message_files(slack, "1.1", ["F1"], markdown="Different words")


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
    # The same completed receipt can repair presentation without changing words.
    source = "**Briefing**\n\n- CI\n  - Tests passed\n\nRead more"
    url = "https://slack.com/docs/F2"
    (tmp_path / "messages").mkdir()
    (tmp_path / "messages/01-toplevel.md").write_text(source)
    (tmp_path / "window.json").write_text(
        json.dumps({"delivery_format": "canvas", "slack_summary_format": "titles"})
    )
    state["canvas"] = {"receipt": {"url": url}}
    slack.message["text"] = daily.mrkdwn(
        source.rsplit("\n", 1)[0] + f"\n[Read more]({url})"
    )
    daily.repair_video_attachment(
        tmp_path, state, slack, saved.append, ["F1"], format_message=True
    )
    assert state["last_cutoff"] == cutoff
    assert state["video_repair"]["formatted"] is True
    assert slack.message["files"] == [{"id": "F1"}]
    formatted = [
        payload for method, payload in slack.calls if "markdown_text" in payload
    ][-1]
    assert formatted["markdown_text"].startswith(
        f"[Your daily briefing canvas]({url})\n\n"
    )
    state["last_cutoff"] = "2026-10-07T05:00:00+00:00"
    with pytest.raises(RuntimeError, match="latest completed"):
        daily.repair_video_attachment(tmp_path, state, slack, saved.append, ["F1"])
