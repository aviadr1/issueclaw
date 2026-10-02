"""Publish prepared report Markdown as a channel-tabbed Slack Canvas."""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

import click
import httpx


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


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def publish(source: str, title: str, channel: str, path: Path, token: str) -> str:
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
                raise click.ClickException(
                    f"Slack {method}: {result.get('error', 'unknown_error')}"
                )
            return result

        if not state.get("canvas_id"):
            state = {"fingerprint": fingerprint, "pending": True}
            save_state(path, state)
            try:
                result = await api(
                    "canvases.create",
                    {
                        "title": title,
                        "channel_id": channel,
                        "document_content": {"type": "markdown", "markdown": source},
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
                raise
            state.pop("pending")
            state["canvas_id"] = result["canvas_id"]
            save_state(path, state)
        if not state.get("url"):
            info = await api("files.info", {"file": state["canvas_id"]})
            url = info["file"]["permalink"]
            if not isinstance(url, str) or not url.startswith("https://"):
                raise click.ClickException(
                    "Slack returned an invalid Canvas permalink."
                )
            state["url"] = url
            save_state(path, state)
        return state["url"]


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
    help="Append the confirmed Canvas link to a prepared message.",
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
) -> None:
    """Create a report Canvas; never send a Slack message.

    Requires canvases:write and files:read on SLACK_BOT_TOKEN. Keep source
    Markdown outside the directory scanned by your Slack message publisher.
    """
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
                text.rstrip() + f"\n\n[Full design report in Slack Canvas]({url})\n",
                encoding="utf-8",
            )
    click.echo(url)
