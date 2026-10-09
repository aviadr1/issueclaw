import asyncio
import hashlib
import json
from unittest.mock import patch

import click
import httpx
import pytest
from click.testing import CliRunner

from issueclaw.main import cli
from issueclaw import slack_canvas, slack_canvas_images


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
        assert "text" not in payload
        assert "\n\n" not in payload["markdown_text"]
        assert payload["markdown_text"].startswith(
            "[Full report in Slack Canvas](https://team.slack.com/docs/F123)"
        )
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


def test_confirmed_legacy_summary_checkpoint_does_not_repost(tmp_path):
    state = tmp_path / "state.json"
    text = "Tickets are ready. [Full report in Slack Canvas](https://team.slack.com/docs/F123)"
    legacy_text = "Tickets are ready. <https://team.slack.com/docs/F123|Full report in Slack Canvas>"
    state.write_text(
        json.dumps(
            {
                "message_fingerprint": hashlib.sha256(
                    json.dumps([legacy_text, "C123", "1790860328.061289"]).encode()
                ).hexdigest(),
                "message_ts": "1790861000.123456",
            }
        )
    )
    with patch.object(
        slack_canvas, "make_client", side_effect=AssertionError("Already published")
    ):
        asyncio.run(
            slack_canvas.post_summary_message(
                text, "C123", "1790860328.061289", state, "secret-test"
            )
        )


@pytest.mark.parametrize(
    "error,pending", [("canvas_creation_failed", False), ("internal_error", True)]
)
def test_canvas_error_preserves_detail_and_only_clears_confirmed_rejections(
    tmp_path, error, pending
):
    detail = "'content' error: line 28: Unsupported block type canvas_creation_failed secret-test"

    def handle(request):
        return httpx.Response(200, json={"ok": False, "error": error, "detail": detail})

    state = tmp_path / "state.json"
    with patch.object(
        slack_canvas,
        "make_client",
        return_value=httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        ),
    ):
        with pytest.raises(
            click.ClickException, match="line 28: Unsupported block type"
        ) as exc:
            asyncio.run(
                slack_canvas.publish("# Report", "Report", "C123", state, "secret-test")
            )
    assert "secret-test" not in str(exc.value)
    assert state.exists() == pending


@pytest.mark.parametrize("depth", [4, 5, 6])
def test_publish_adapts_deep_headings_without_changing_media_or_code(tmp_path, depth):
    heading = "#" * depth + " Gallery"
    source = (
        f"# Report\n\n{heading}\n\n"
        "![State](https://example.com/state.png)\n"
        "[Explore](https://example.com/#/feed)\n\n"
        f"```markdown\n{heading}\n```\n\n"
        f"~~~~\n{heading}\n~~~\n~~~~\n"
    )
    expected = source.replace(heading, "### Gallery", 1)
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("canvases.create"):
            assert (
                json.loads(request.content)["document_content"]["markdown"] == expected
            )
            return httpx.Response(200, json={"ok": True, "canvas_id": "F123"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"permalink": "https://team.slack.com/docs/F123"},
            },
        )

    def client(_token):
        return httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        )

    state = tmp_path / "state.json"
    with patch.object(slack_canvas, "make_client", side_effect=client):
        first = asyncio.run(
            slack_canvas.publish(source, "Report", "C123", state, "secret-test")
        )
        assert (
            asyncio.run(
                slack_canvas.publish(source, "Report", "C123", state, "secret-test")
            )
            == first
        )
    assert len(calls) == 2


@pytest.mark.parametrize("lost_completion", [False, True])
def test_manifest_images_upload_once_and_repair_existing_canvas_without_reposting(
    tmp_path,
    lost_completion,
):
    image_url = "https://example.com/capture.png"
    permalink = "https://team.slack.com/files/U123/FIMAGE/capture.png"
    image = tmp_path / "capture.png"
    image.write_bytes(b"PNG capture bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "captures": [
                    {
                        "hosted_url": image_url,
                        "file": image.name,
                        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    }
                ]
            }
        )
    )
    source = f"# Report\n\n![Feed]({image_url})\n\n[Full size]({image_url})"
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "fingerprint": hashlib.sha256(
                    json.dumps([source, "Report", "C123"]).encode()
                ).hexdigest(),
                "canvas_id": "FCANVAS",
                "url": "https://team.slack.com/docs/FCANVAS",
                "message_ts": "123.456789",
            }
        )
    )
    calls = []

    def handle(request):
        method = request.url.path.split("/")[-1]
        calls.append(method)
        if method == "files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file_id": "FIMAGE",
                    "upload_url": "https://files.slack.com/upload",
                },
            )
        if method == "files.completeUploadExternal":
            assert b"channel_id" not in request.content
            if lost_completion:
                raise httpx.ReadTimeout("completion response lost")
            return httpx.Response(200, json={"ok": True})
        if method == "files.info":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {
                        "permalink": permalink,
                        "mimetype": "image/png",
                        "original_w": 100,
                        "original_h": 100,
                    },
                },
            )
        assert method == "canvases.edit"
        payload = json.loads(request.content)
        assert payload["canvas_id"] == "FCANVAS"
        markdown = payload["changes"][0]["document_content"]["markdown"]
        assert f"![Feed]({permalink})" in markdown
        assert f"[Full size]({image_url})" in markdown
        return httpx.Response(200, json={"ok": True})

    def client(_token):
        return httpx.AsyncClient(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        )

    # Patch external transport only; exercise real file hashing/upload/rewrite/state.
    real_client = httpx.Client

    def sync_client(*args, **kwargs):
        return real_client(
            base_url="https://slack.com/api/", transport=httpx.MockTransport(handle)
        )

    with (
        patch.object(slack_canvas, "make_client", side_effect=client),
        patch.object(httpx, "Client", side_effect=sync_client),
        patch.object(
            httpx,
            "post",
            return_value=httpx.Response(
                200, request=httpx.Request("POST", "https://files.slack.com/upload")
            ),
        ) as upload,
    ):
        if lost_completion:
            with pytest.raises(httpx.ReadTimeout):
                asyncio.run(
                    slack_canvas.publish(
                        source,
                        "Report",
                        "C123",
                        state_path,
                        "secret-test",
                        image_manifest=manifest,
                        refresh_media=True,
                    )
                )
        for _ in range(2):
            asyncio.run(
                slack_canvas.publish(
                    source,
                    "Report",
                    "C123",
                    state_path,
                    "secret-test",
                    image_manifest=manifest,
                    refresh_media=True,
                )
            )
    assert calls.count("files.getUploadURLExternal") == 1
    assert calls.count("canvases.edit") == 1
    assert upload.call_args.kwargs["content"] == image.read_bytes()
    assert "Authorization" not in upload.call_args.kwargs.get("headers", {})
    assert json.loads(state_path.read_text())["message_ts"] == "123.456789"


@pytest.mark.parametrize("failure", ["missing", "changed", "escape"])
def test_invalid_capture_cannot_trigger_upload(tmp_path, failure):
    url = "https://example.com/image.png"
    image = tmp_path / "image.png"
    image.write_bytes(b"capture")
    row = {
        "hosted_url": url,
        "file": image.name,
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    if failure == "changed":
        image.write_bytes(b"changed")
    if failure == "escape":
        row["file"] = "../image.png"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"captures": [] if failure == "missing" else [row]}))
    with patch.object(
        httpx, "Client", side_effect=AssertionError("must validate before upload")
    ):
        with pytest.raises(click.ClickException):
            asyncio.run(
                slack_canvas.publish(
                    f"![Image]({url})",
                    "Report",
                    "C123",
                    tmp_path / "state.json",
                    "secret-test",
                    image_manifest=manifest,
                )
            )


def test_native_image_waits_for_processing_before_embedding():
    responses = iter(
        [
            {"permalink": "https://team.slack.com/files/U123/FIMAGE", "mimetype": ""},
            {
                "permalink": "https://team.slack.com/files/U123/FIMAGE",
                "mimetype": "image/png",
            },
        ]
    )

    class Files:
        def file_info(self, file_id):
            assert file_id == "FIMAGE"
            return next(responses)

    with patch.object(slack_canvas_images.time, "sleep"):
        assert (
            slack_canvas_images.image_info(Files(), "FIMAGE")["mimetype"] == "image/png"
        )
