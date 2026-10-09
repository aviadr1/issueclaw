"""Shared Slack file upload transport for report images and learning videos."""

import json
import re

import httpx


class SlackRejected(RuntimeError):
    """Slack explicitly rejected a message without accepting it."""


def mrkdwn(text):
    """Markdown links and bold as Slack mrkdwn."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<\2|\1>", text)
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)


class SlackFiles:
    def __init__(self, channel, token):
        self.channel = channel
        self.client = httpx.Client(
            base_url="https://slack.com/api/",
            timeout=60,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.history = None

    def call(self, method, data, get=False):
        """File methods take form fields (or query parameters), not JSON."""
        response = (
            self.client.get(method, params=data)
            if get
            else self.client.post(method, data=data)
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise SlackRejected(
                f"Slack {method}: {result.get('error', 'unknown error')}"
            )
        return result

    def start_upload(self, path):
        """Send a file's bytes to Slack; it is discarded unless completed."""
        size = path.stat().st_size
        ticket = self.call(
            "files.getUploadURLExternal", {"filename": path.name, "length": size}
        )
        response = httpx.post(
            ticket["upload_url"], content=path.read_bytes(), timeout=300
        )
        response.raise_for_status()
        return ticket["file_id"]

    def complete_upload(self, file, title, comment=None, thread=None, share=True):
        data = {"files": json.dumps([{"id": file, "title": title}])}
        if share:
            data["channel_id"] = self.channel
        if comment is not None:
            data["initial_comment"] = mrkdwn(comment)
        if thread:
            data["thread_ts"] = thread
        self.call("files.completeUploadExternal", data)
        self.history = None

    def file_info(self, file):
        return self.call("files.info", {"file": file}, get=True)["file"]
