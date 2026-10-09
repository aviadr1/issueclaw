"""Publish prepared report Markdown as a channel-tabbed Slack Canvas."""

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path

import click
import httpx
from markdown_it import MarkdownIt


def make_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://slack.com/api/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def validate_content(content: str) -> None:
    if not content.strip() or len(content) > 1_048_576:
        raise click.ClickException(
            "Canvas Markdown must contain 1–1,048,576 characters."
        )
    if re.search(r"```\s*mermaid|!\[[^\]]*\]\((?!https://)", content):
        raise click.ClickException(
            "Replace Mermaid with prose and use HTTPS image URLs accessible to Slack."
        )


def canvas_markdown(source: str) -> str:
    """Adapt real Markdown headings to Canvas's h1–h3 limit, preserving code.

    Parse block structure rather than replacing hash marks inside code fences,
    images or links. Keep the original source for the durable retry fingerprint.
    """
    lines = source.splitlines(keepends=True)
    for block in MarkdownIt().parse(source):
        if (
            block.type == "heading_open"
            and block.tag in {"h4", "h5", "h6"}
            and block.map
        ):
            index = block.map[0]
            lines[index] = re.sub(r"#{4,6}(?=[ \t]|$)", "###", lines[index], count=1)
    return "".join(lines)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def publish(
    source: str,
    title: str,
    channel: str,
    path: Path,
    token: str,
    *,
    on_save: Callable[[dict], None] | None = None,
) -> str:
    fingerprint = hashlib.sha256(
        json.dumps([source, title, channel]).encode()
    ).hexdigest()
    state = json.loads(path.read_text()) if path.exists() else {}
    if state and state.get("fingerprint") != fingerprint:
        raise click.ClickException(
            "Saved Canvas state belongs to different content or destination."
        )
    if state.get("pending"):
        raise click.ClickException(
            "Canvas creation outcome is unknown. Inspect Slack before retrying; "
            "record the recovered canvas_id and remove pending in the state file."
        )

    def checkpoint():
        save_state(path, state)
        if on_save:
            on_save(state)

    async with make_client(token) as client:

        async def api(method: str, payload: dict) -> dict:
            response = (
                await client.get(method, params=payload)
                if method == "files.info"
                else await client.post(method, json=payload)
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                # Slack returns the rejected Markdown node/line in `detail`.
                # Preserve that diagnostic, without dumping the response or token.
                detail = str(result.get("detail") or "").replace(token, "[redacted]")
                raise click.ClickException(
                    f"Slack {method}: {result.get('error', 'unknown_error')}"
                    + (f" — {detail}" if detail else "")
                )
            return result

        if not state.get("canvas_id"):
            state = {"fingerprint": fingerprint, "pending": True}
            checkpoint()
            try:
                result = await api(
                    "canvases.create",
                    {
                        "title": title,
                        "channel_id": channel,
                        "document_content": {
                            "type": "markdown",
                            "markdown": canvas_markdown(source),
                        },
                    },
                )
            except click.ClickException as exc:
                # These responses explicitly reject creation, so a corrected retry is safe.
                if any(
                    code in str(exc)
                    for code in (
                        "missing_scope",
                        "invalid_auth",
                        "not_authed",
                        "canvas_creation_failed",
                        "free_team_canvas_tab_already_exists",
                    )
                ):
                    path.unlink()
                    if on_save:
                        on_save({})
                raise
            state.pop("pending")
            state["canvas_id"] = result["canvas_id"]
            checkpoint()
        if not state.get("url"):
            info = await api("files.info", {"file": state["canvas_id"]})
            url = info["file"]["permalink"]
            if not isinstance(url, str) or not url.startswith("https://"):
                raise click.ClickException(
                    "Slack returned an invalid Canvas permalink."
                )
            state["url"] = url
            checkpoint()
        return state["url"]


def markdown_message_payload(text: str, channel: str, thread_ts: str = "") -> dict:
    """Keep native Markdown and Canvas rendering consistent across publishers."""
    payload = {
        "channel": channel,
        "markdown_text": text,
        "unfurl_links": False,
        "unfurl_media": False,
        "reply_broadcast": False,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return payload


async def post_summary_message(
    text: str, channel: str, thread_ts: str, path: Path, token: str
) -> None:
    state = json.loads(path.read_text())
    text = text.strip()
    # Retain the original fingerprint encoding so pre-upgrade checkpoints resume.
    fingerprint_text = re.sub(r"\[([^\]]+)\]\((https://[^)]+)\)", r"<\2|\1>", text)
    fingerprint = hashlib.sha256(
        json.dumps([fingerprint_text, channel, thread_ts]).encode()
    ).hexdigest()
    if state.get("message_fingerprint") not in (None, fingerprint):
        raise click.ClickException(
            "Saved summary state belongs to another message destination or content."
        )
    if state.get("message_ts"):
        return
    if state.get("message_pending"):
        raise click.ClickException(
            "Summary posting outcome is unknown; inspect Slack before retrying."
        )
    state.update(message_fingerprint=fingerprint, message_pending=True)
    save_state(path, state)
    payload = markdown_message_payload(text, channel, thread_ts)
    async with make_client(token) as client:
        response = await client.post("chat.postMessage", json=payload)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            if result.get("error") not in (
                "fatal_error",
                "internal_error",
                "request_timeout",
            ):
                state.pop("message_pending")
                save_state(path, state)
            raise click.ClickException(
                f"Slack chat.postMessage: {result.get('error', 'unknown_error')}"
            )
        state.pop("message_pending")
        state["message_ts"] = result["ts"]
        save_state(path, state)


@click.command("slack-canvas")
@click.option(
    "--source",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--title", required=True)
@click.option(
    "--channel",
    required=True,
    help="Regular channel to receive a Canvas tab (channel members can edit).",
)
@click.option(
    "--state",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Persist and reuse this file on retries.",
)
@click.option(
    "--summary",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Put the confirmed Canvas link first in a prepared message.",
)
@click.option(
    "--post-summary",
    is_flag=True,
    help="Post the prepared TLDR after Canvas creation (chat:write required).",
)
@click.option(
    "--thread-ts",
    default="",
    help="Reply within this parent thread; never broadcast the reply.",
)
@click.option(
    "--dry-run", is_flag=True, help="Validate content without contacting Slack."
)
def slack_canvas_command(
    source: Path,
    title: str,
    channel: str,
    state: Path,
    summary: Path | None,
    dry_run: bool,
    post_summary: bool,
    thread_ts: str,
) -> None:
    """Create a report Canvas; optionally post its TLDR to a channel or thread.

    Requires canvases:write and files:read on SLACK_BOT_TOKEN. Keep source
    Markdown outside the directory scanned by your Slack message publisher.
    """
    if post_summary and not summary:
        raise click.ClickException("--post-summary requires --summary.")
    if thread_ts and (
        not post_summary or not re.fullmatch(r"[0-9]+\.[0-9]{6}", thread_ts)
    ):
        raise click.ClickException(
            "--thread-ts requires --post-summary and a valid Slack timestamp."
        )
    if post_summary and summary:
        summary_text = summary.read_text(encoding="utf-8").strip()
        if not summary_text or "\n\n" in summary_text:
            raise click.ClickException(
                "The posted TLDR must be one nonempty paragraph."
            )
    content = source.read_text(encoding="utf-8")
    validate_content(content)
    if dry_run:
        click.echo("Canvas Markdown validated; nothing published.")
        return
    token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_MCP_XOXB_TOKEN")
    if not token:
        raise click.ClickException(
            "Set SLACK_BOT_TOKEN (canvases:write and files:read)."
        )
    try:
        url = asyncio.run(publish(content, title, channel, state, token))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise click.ClickException(
            f"Slack Canvas publishing failed ({type(exc).__name__}); inspect saved state before retrying."
        ) from exc
    if summary:
        text = summary.read_text(encoding="utf-8")
        if url not in text:
            summary.write_text(
                f"[Full report in Slack Canvas]({url}) " + text.strip() + "\n",
                encoding="utf-8",
            )
    if post_summary and summary:
        try:
            asyncio.run(
                post_summary_message(
                    summary.read_text(encoding="utf-8"),
                    channel,
                    thread_ts,
                    state,
                    token,
                )
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise click.ClickException(
                f"Summary publishing failed ({type(exc).__name__}); inspect saved state before retrying."
            ) from exc
    click.echo(url)
