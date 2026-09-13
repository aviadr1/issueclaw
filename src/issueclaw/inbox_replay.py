"""Replay dirty entities; remotely committed per-key receipts authorize ACKs."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import time

import httpx

from issueclaw.entity_changes import apply_changes, checked_path, prepare_entity
from issueclaw.inbox_contract import Batch, Outcome

CHECKPOINT = ".sync/inbox-checkpoint.json"
PUBLICATION_RESERVE_SECONDS = 60
logger = logging.getLogger(__name__)


class InboxClient:
    def __init__(self, url: str, token: str):
        if not url.startswith("https://"):
            raise ValueError("Inbox URL must use HTTPS")
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def post(self, path: str, body: dict | None = None) -> dict:
        response = httpx.post(
            self.url + "/inbox/" + path,
            headers=self.headers,
            json=body or {},
            timeout=30,
        )
        response.raise_for_status()
        return (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )

    def claim(self) -> Batch | None:
        response = httpx.post(
            self.url + "/inbox/claim", headers=self.headers, timeout=30
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return Batch.model_validate(response.json())

    def ack(self, token: str, results: list[Outcome]) -> None:
        response = httpx.post(
            self.url + "/inbox/ack",
            headers=self.headers,
            json={"token": token, "results": [r.model_dump() for r in results]},
            timeout=30,
        )
        response.raise_for_status()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def drain(
    inbox, repo: Path, api_key: str, *, deadline: float | None = None
) -> list[Outcome] | None:
    """Publish healthy keys together; retain failed keys independently.

    Only a clean checkout equal to remote main can supply receipts. Preparation
    is isolated per entity; publication and ACK failures abort the entire run.
    A later runner can safely ACK receipts even when the prior ACK was lost.
    """
    if git(repo, "status", "--porcelain"):
        raise ValueError("Replay requires a clean disposable checkout")
    git(repo, "fetch", "origin", "main")
    git(repo, "merge", "--ff-only", "origin/main")
    if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "origin/main"):
        raise ValueError("Checkout differs from remote main; use a fresh checkout")
    if deadline is not None and time.monotonic() >= deadline:
        return None
    batch = inbox.claim()
    if batch is None:
        return None
    checkpoint_path = checked_path(repo, CHECKPOINT)
    checkpoint = (
        json.loads(checkpoint_path.read_text())
        if checkpoint_path.exists()
        else {"stream": batch.stream, "receipts": {}}
    )
    if checkpoint["stream"] != batch.stream or "receipts" not in checkpoint:
        raise ValueError(
            "Inbox stream/format changed; explicit reconciliation required"
        )
    receipts = checkpoint["receipts"]
    changed = False

    async def prepare_and_apply() -> list[Outcome]:
        nonlocal changed
        outcomes = []
        preparation_deadline = time.monotonic() + 120
        if deadline is not None:
            # The caller's shared deadline also fences work *inside* a batch;
            # checking only between batches can overrun the hosted job timeout.
            preparation_deadline = min(preparation_deadline, deadline)
        for item in batch.items:
            if receipts.get(item.key, 0) >= item.generation:
                outcomes.append(Outcome(key=item.key, success=True))
                continue
            remaining = preparation_deadline - time.monotonic()
            if remaining <= 0:
                outcomes.append(Outcome(key=item.key, success=False))
                continue
            try:
                changes = await asyncio.wait_for(
                    prepare_entity(item.payload.model_dump(), api_key, repo),
                    timeout=min(20, remaining),
                )
            except Exception as error:
                # Scratch isolation prevents a failed key contaminating another.
                # Never print source payloads or API error bodies.
                logger.error("Entity preparation failed (%s)", type(error).__name__)
                outcomes.append(Outcome(key=item.key, success=False))
                continue
            apply_changes(repo, changes)  # disk failure is publication-fatal
            receipts[item.key] = item.generation
            changed = True
            outcomes.append(Outcome(key=item.key, success=True))
        return outcomes

    outcomes = asyncio.run(prepare_and_apply())
    if changed:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True) + "\n")
        git(repo, "add", "-A", "--", ".sync")
        if (repo / "linear").exists() or git(repo, "ls-files", "linear"):
            git(repo, "add", "-A", "--", "linear")
        git(repo, "commit", "-m", "sync: reconcile inbox entity generations")
        git(repo, "push", "origin", "HEAD:main")
    inbox.ack(batch.token, outcomes)
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    inbox = InboxClient(os.environ["INBOX_URL"], os.environ["INBOX_TOKEN"])
    deadline = time.monotonic() + 180
    if job_deadline := os.environ.get("ISSUECLAW_JOB_DEADLINE"):
        # Discovery/setup already spent part of the same CI job. Preserve time
        # for publishing prepared receipts and ACK; never grant a fresh budget.
        remaining = float(job_deadline) - time.time() - PUBLICATION_RESERVE_SECONDS
        deadline = min(deadline, time.monotonic() + remaining)
    failed = False
    for _ in range(10):
        if time.monotonic() >= deadline:
            break
        outcomes = drain(
            inbox, args.repo_dir, os.environ["LINEAR_API_KEY"], deadline=deadline
        )
        if outcomes is None:
            break
        failed |= any(not outcome.success for outcome in outcomes)
    if failed:
        raise SystemExit("Some entities remain pending; inspect inbox status")


if __name__ == "__main__":
    main()
