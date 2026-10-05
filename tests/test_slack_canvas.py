import json
from unittest.mock import patch

import httpx
import pytest
from click.testing import CliRunner

from issueclaw.main import cli
from issueclaw import slack_canvas


@pytest.mark.parametrize("fail_info", [False, True])
def test_publish_and_resume(tmp_path, fail_info):
    source = tmp_path / "canvas.md"
    source.write_text(
        "# Design\n\n| Platform | State |\n| --- | --- |\n| Native mobile | Merged |\n\n![Tickets](https://example.com/tickets.png)"
    )
    state = tmp_path / "state.json"
    summary = tmp_path / "summary.md"
    summary.write_text("This week: native tickets moved to implementation.\n")
    calls = []

    def handle(request):
        method = request.url.path.split("/")[-1]
        calls.append(method)
        if method == "canvases.create":
            payload = json.loads(request.content)
            assert payload["channel_id"] == "C123"
            assert payload["document_content"]["markdown"] == source.read_text()
            return httpx.Response(200, json={"ok": True, "canvas_id": "F123"})
        assert method == "files.info"
        if fail_info and calls.count("files.info") == 1:
            return httpx.Response(200, json={"ok": False, "error": "missing_scope"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"permalink": "https://team.slack.com/docs/F123"},
            },
        )

    client = httpx.AsyncClient(
        base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
    )
    args = [
        "slack-canvas",
        "--source",
        str(source),
        "--title",
        "Design weekly",
        "--channel",
        "C123",
        "--state",
        str(state),
        "--summary",
        str(summary),
    ]
    with patch.object(slack_canvas, "make_client", return_value=client):
        result = CliRunner().invoke(cli, args, env={"SLACK_BOT_TOKEN": "secret-test"})
        if fail_info:
            assert result.exit_code != 0
            assert "missing_scope" in result.output
            assert "https://team" not in summary.read_text()
            assert json.loads(state.read_text())["canvas_id"] == "F123"
            client = httpx.AsyncClient(
                base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
            )
            with patch.object(slack_canvas, "make_client", return_value=client):
                result = CliRunner().invoke(
                    cli, args, env={"SLACK_BOT_TOKEN": "secret-test"}
                )
        assert result.exit_code == 0, result.output
    assert calls.count("canvases.create") == 1
    assert summary.read_text().count("https://team.slack.com/docs/F123") == 1
    assert "\n\n" not in summary.read_text()
    assert "secret-test" not in state.read_text() + result.output


@pytest.mark.parametrize(
    "content",
    ["", "```mermaid\ngraph LR\n```", "![Local](file:///tmp/image.png)", "x" * 1048577],
    ids=["empty", "mermaid", "local-image", "oversized"],
)
def test_invalid_content_rejected_before_network(tmp_path, content):
    source = tmp_path / "canvas.md"
    source.write_text(content)
    result = CliRunner().invoke(
        cli,
        [
            "slack-canvas",
            "--source",
            str(source),
            "--title",
            "Design",
            "--channel",
            "C123",
            "--state",
            str(tmp_path / "state.json"),
            "--dry-run",
        ],
    )
    assert result.exit_code != 0


def test_unknown_create_outcome_cannot_duplicate_on_retry(tmp_path):
    source = tmp_path / "canvas.md"
    source.write_text("# Design")
    state = tmp_path / "state.json"
    args = [
        "slack-canvas",
        "--source",
        str(source),
        "--title",
        "Design",
        "--channel",
        "C123",
        "--state",
        str(state),
    ]
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout")

    with patch.object(
        slack_canvas,
        "make_client",
        return_value=httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        ),
    ):
        first = CliRunner().invoke(cli, args, env={"SLACK_BOT_TOKEN": "secret-test"})
        second = CliRunner().invoke(cli, args, env={"SLACK_BOT_TOKEN": "secret-test"})
    assert first.exit_code != 0
    assert second.exit_code != 0
    assert "unknown" in second.output
    assert len(calls) == 1


@pytest.mark.parametrize("thread", ["", "1790860328.061289"], ids=["channel", "thread"])
def test_summary_destination_and_retry(tmp_path, thread):
    source = tmp_path / "canvas.md"
    source.write_text("# Design\n\nNative mobile tickets reached implementation.")
    summary = tmp_path / "summary.md"
    summary.write_text("Native mobile tickets reached implementation.\n")
    state = tmp_path / "state.json"
    messages = []

    def handle(request):
        method = request.url.path.split("/")[-1]
        if method == "canvases.create":
            return httpx.Response(200, json={"ok": True, "canvas_id": "F123"})
        if method == "files.info":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {"permalink": "https://team.slack.com/docs/F123"},
                },
            )
        assert method == "chat.postMessage"
        payload = json.loads(request.content)
        messages.append(payload)
        assert payload["channel"] == "C123"
        assert payload.get("thread_ts", "") == thread
        assert not payload.get("reply_broadcast", False)
        assert "\n\n" not in payload["text"]
        assert "<https://team.slack.com/docs/F123|" in payload["text"]
        return httpx.Response(200, json={"ok": True, "ts": "1790861000.123456"})

    args = [
        "slack-canvas",
        "--source",
        str(source),
        "--title",
        "Design",
        "--channel",
        "C123",
        "--state",
        str(state),
        "--summary",
        str(summary),
        "--post-summary",
    ]
    if thread:
        args += ["--thread-ts", thread]
    with patch.object(
        slack_canvas,
        "make_client",
        side_effect=lambda token: httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        ),
    ):
        for _ in range(2):
            result = CliRunner().invoke(
                cli, args, env={"SLACK_BOT_TOKEN": "secret-test"}
            )
            assert result.exit_code == 0, result.output
    assert len(messages) == 1
    assert json.loads(state.read_text())["message_ts"] == "1790861000.123456"
