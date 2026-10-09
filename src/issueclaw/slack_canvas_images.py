"""Stage selected, hash-verified report captures as native Slack image files."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import click
from markdown_it import MarkdownIt

from issueclaw.slack_files import SlackFiles, SlackRejected


def prepare_images(source, manifest_path, receipts, save, token):
    """Preserve public links; replace image embeds only. Never fetch arbitrary URLs.

    The collector manifest maps hosted_url to a relative local file and SHA-256.
    File IDs are checkpointed before completion; a retry recovers that upload
    instead of producing more files. Uploads remain private until embedded in
    the channel's Canvas, with no per-image channel messages.
    """
    manifest_path = Path(manifest_path)
    captures = {
        r.get("hosted_url"): r
        for r in json.loads(manifest_path.read_text())["captures"]
    }
    blocks = MarkdownIt().parse(source)
    images = {}
    for block in blocks:
        for child in block.children or []:
            if child.type == "image":
                url = str(child.attrGet("src") or "")
                if (urlparse(url).hostname or "").endswith(".slack.com"):
                    continue
                if url:
                    images[url] = child.content
    # Validate every selected local file before making the first upload.
    files = {}
    for url in images:
        row = captures.get(url)
        if not row:
            raise click.ClickException(
                f"Embedded image is missing from the capture manifest: {url}"
            )
        path = (manifest_path.parent / row["file"]).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()):
            raise click.ClickException("Capture path escapes the media directory.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            raise click.ClickException(f"Capture bytes changed: {path.name}")
        files[url] = (path, digest)
    slack = SlackFiles("", token)
    try:
        for url, (path, digest) in files.items():
            receipt = receipts.setdefault(url, {"sha256": digest})
            if receipt["sha256"] != digest:
                raise click.ClickException(
                    "Saved Slack image belongs to different bytes."
                )
            if receipt.get("permalink"):
                continue
            if not receipt.get("file"):
                receipt["file"] = slack.start_upload(path)
                save()
            if receipt.get("complete_pending"):
                # Completion can succeed even when its HTTP response is lost.
                # files.info distinguishes a completed file from a pending upload.
                info = slack.file_info(receipt["file"])
                if not info.get("permalink"):
                    raise click.ClickException(
                        "Image completion is unresolved; retry after Slack finishes processing."
                    )
            else:
                receipt["complete_pending"] = True
                save()
                slack.complete_upload(
                    receipt["file"], images[url] or path.name, share=False
                )
                info = slack.file_info(receipt["file"])
            if not str(info.get("mimetype", "")).startswith("image/"):
                raise click.ClickException(
                    "Slack did not recognize the uploaded capture as an image."
                )
            permalink = info.get("permalink", "")
            if not permalink.startswith("https://"):
                raise click.ClickException("Slack image has no usable permalink.")
            receipt.update(permalink=permalink)
            receipt.pop("complete_pending", None)
            save()
    except SlackRejected as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        slack.client.close()
    # Inline block maps exclude fenced code. Ordinary full-size links remain public.
    lines = source.splitlines(keepends=True)
    for block in reversed(blocks):
        if (
            block.type != "inline"
            or not block.map
            or not any(c.type == "image" for c in block.children or [])
        ):
            continue
        start, end = block.map
        text = "".join(lines[start:end])
        text = re.sub(
            r"!\[([^\]]*)\]\((https://[^\s)]+)\)",
            lambda m: (
                f"![{m[1]}]({receipts[m[2]]['permalink']})"
                if m[2] in receipts
                else m[0]
            ),
            text,
        )
        lines[start:end] = [text]
    return "".join(lines)
