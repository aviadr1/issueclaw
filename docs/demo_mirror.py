"""Write a fixture Linear mirror for the README demo, without a Linear API key.

Files are written with the same path, render, and sync-state functions that
`issueclaw pull` uses, so `issueclaw status` and `issueclaw diff` read the
result like a real mirror. Used by docs/demo.tape and
tests/test_demo_mirror.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

from issueclaw.models import LinearComment, LinearIssue
from issueclaw.paths import entity_path
from issueclaw.render import render_issue
from issueclaw.sync_state import SyncState


def fixture_issues() -> list[LinearIssue]:
    """Sample issues for the terminal demo."""
    return [
        LinearIssue(
            id="fixture-eng-14",
            identifier="ENG-14",
            title="Fix login timeout on session refresh",
            description=(
                "Users are signed out when the login token expires during refresh."
            ),
            status="In Progress",
            priority=2,
            assignee="dev",
            labels=["bug", "auth"],
            team="ENG",
            team_key="ENG",
            project="Auth",
            created="2026-09-01T10:00:00Z",
            updated="2026-09-20T15:00:00Z",
            url="https://linear.app/example/issue/ENG-14",
            comments=[
                LinearComment(
                    id="fixture-comment-1",
                    body="Refresh drops the login cookie when the clock skews.",
                    author_name="dev",
                    created="2026-09-20T15:00:00Z",
                )
            ],
        ),
        LinearIssue(
            id="fixture-eng-31",
            identifier="ENG-31",
            title="Retry failed webhook deliveries",
            description="Deliveries that return 500 should retry with backoff.",
            status="Todo",
            priority=3,
            assignee="dev",
            labels=["reliability"],
            team="ENG",
            team_key="ENG",
            created="2026-09-12T09:00:00Z",
            updated="2026-09-18T11:00:00Z",
            url="https://linear.app/example/issue/ENG-31",
        ),
        LinearIssue(
            id="fixture-eng-8",
            identifier="ENG-8",
            title="Search the local markdown mirror",
            description="Agents should search linear/** instead of paging the API.",
            status="Done",
            priority=4,
            team="ENG",
            team_key="ENG",
            created="2026-08-02T09:00:00Z",
            updated="2026-08-20T09:00:00Z",
            url="https://linear.app/example/issue/ENG-8",
        ),
    ]


def mirror(repo_dir: Path) -> list[str]:
    """Render fixture issues into repo_dir/linear and record sync state."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    state = SyncState(repo_dir)
    state.load()
    written: list[str] = []
    for issue in fixture_issues():
        if not issue.team_key:
            raise ValueError(f"{issue.identifier} is missing team_key")
        path = entity_path(
            "issue",
            team_key=issue.team_key,
            identifier=issue.identifier,
            issue_title=issue.title,
        )
        state.write_entity(path, issue.id, render_issue(issue))
        written.append(path)
    state.set_last_sync("2026-09-27T00:00:00Z")
    state.save()
    return written


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: demo_mirror.py REPO_DIR", file=sys.stderr)
        raise SystemExit(2)
    repo_dir = Path(args[0])
    paths = mirror(repo_dir)
    print(f"mirrored {len(paths)} issues into {repo_dir}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
