"""Bounded, read-only preparation of an exported inbox snapshot.

Input is a JSON array of WorkItem objects (key, generation, payload), not event
receipts or a claim token. No inbox client or publication operation is used.
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Literal

from pydantic import TypeAdapter

from issueclaw.entity_changes import prepare_entity
from issueclaw.inbox_contract import WorkItem
from issueclaw.sync_state import IdentityConflict


@dataclass(frozen=True)
class PreviewResult:
    key: str
    outcome: Literal["changes", "noop", "identity_conflict", "timeout", "error"]
    file_changes: int = 0
    error_type: str | None = None


async def preview(
    items: list[WorkItem], repo: Path, api_key: str, *, limit: int = 10
) -> list[PreviewResult]:
    """Reuse isolated preparation, never apply its returned file changes.

    At most 25 owners and 60 seconds of preparation per invocation. This bounds
    source reads, not their exact count (one owner can require multiple pages).
    A no-op is an observation, never permission to ACK or discard queued work.
    """
    if not 1 <= limit <= 25:
        raise ValueError("Preview limit must be between 1 and 25")
    deadline = time.monotonic() + 60
    results = []
    for item in items[:limit]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            changes = await asyncio.wait_for(
                prepare_entity(item.payload.model_dump(), api_key, repo),
                timeout=min(20, remaining),
            )
            results.append(
                PreviewResult(item.key, "changes" if changes else "noop", len(changes))
            )
        except IdentityConflict:
            results.append(PreviewResult(item.key, "identity_conflict"))
        except TimeoutError:
            results.append(PreviewResult(item.key, "timeout"))
        except Exception as error:
            # API exceptions can contain source content/secrets. Export only
            # the exception class, never its message or the original payload.
            results.append(
                PreviewResult(item.key, "error", error_type=type(error).__name__)
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items-file", type=Path, required=True)
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    items = TypeAdapter(list[WorkItem]).validate_json(args.items_file.read_text())
    results = asyncio.run(
        preview(items, args.repo_dir, os.environ["LINEAR_API_KEY"], limit=args.limit)
    )
    print(
        json.dumps(
            {
                "input_owners": len(items),
                "previewed": len(results),
                "outcomes": dict(Counter(result.outcome for result in results)),
                "error_types": dict(
                    Counter(
                        result.error_type for result in results if result.error_type
                    )
                ),
                "file_changes": sum(result.file_changes for result in results),
                "published": False,
                "claimed": False,
                "acknowledged": False,
            }
        )
    )


if __name__ == "__main__":
    main()
