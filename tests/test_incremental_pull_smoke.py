"""Integration/smoke tests for incremental pull durability invariants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands.pull import _run_pull


LAST_SYNC_TS = "2026-04-09T08:00:00Z"
TEAM_ENG = {"id": "team-eng", "key": "ENG", "name": "Engineering"}


def _issue_payload() -> dict:
    return {
        "id": "issue-1",
        "identifier": "ENG-42",
        "title": "Incremental smoke",
        "description": "Issue updated after last sync.",
        "priority": 2,
        "priorityLabel": "High",
        "url": "https://linear.app/gigaverse/issue/ENG-42/incremental-smoke",
        "createdAt": "2026-04-01T10:00:00Z",
        "updatedAt": "2026-04-09T08:05:00Z",
        "state": {"name": "In Progress"},
        "assignee": {"id": "user-1", "name": "Aviad"},
        "labels": {"nodes": [{"name": "Feature"}]},
        "team": {"id": "team-eng", "key": "ENG", "name": "Engineering"},
        "project": None,
        "projectMilestone": None,
        "parent": None,
        "comments": {
            "nodes": [
                {
                    "id": "comment-1",
                    "body": "Edited comment body",
                    "createdAt": "2026-04-09T08:04:00Z",
                    "updatedAt": "2026-04-09T08:05:00Z",
                    "user": {"id": "user-2", "name": "Dana"},
                }
            ]
        },
    }


def _project_payload() -> dict:
    return {
        "id": "project-1",
        "name": "Platform Reboot",
        "slugId": "platform-reboot",
        "description": "Project description",
        "content": "# Project\n\nIncremental update.",
        "priority": 2,
        "health": "onTrack",
        "progress": 0.55,
        "scope": 30,
        "status": {"name": "In Progress"},
        "lead": {"id": "user-1", "name": "Aviad"},
        "url": "https://linear.app/gigaverse/project/platform-reboot",
        "createdAt": "2026-03-01T00:00:00Z",
        "updatedAt": "2026-04-09T08:06:00Z",
        "teams": {"nodes": [{"key": "ENG", "name": "Engineering"}]},
        "members": {"nodes": [{"name": "Aviad"}]},
        "labels": {"nodes": [{"name": "Foundation"}]},
        "projectMilestones": {"nodes": []},
        "projectUpdates": {"nodes": []},
        "initiatives": {"nodes": []},
        "documents": {"nodes": []},
    }


def _initiative_payload() -> dict:
    return {
        "id": "initiative-1",
        "name": "2026 Platform Drive",
        "description": "Initiative description",
        "content": "Initiative content",
        "status": "Active",
        "health": "onTrack",
        "targetDate": "2026-12-31",
        "url": "https://linear.app/gigaverse/initiative/2026-platform-drive",
        "createdAt": "2026-03-01T00:00:00Z",
        "updatedAt": "2026-04-09T08:07:00Z",
        "owner": {"id": "user-1", "name": "Aviad"},
        "projects": {"nodes": [{"id": "project-1", "name": "Platform Reboot"}]},
    }


def _document_payload() -> dict:
    return {
        "id": "document-1",
        "title": "Incremental Sync Playbook",
        "content": "# Playbook\n\nFresh content from incremental sync.",
        "slugId": "incremental-sync-playbook",
        "url": "https://linear.app/gigaverse/document/incremental-sync-playbook",
        "createdAt": "2026-03-01T00:00:00Z",
        "updatedAt": "2026-04-09T08:08:00Z",
        "creator": {"id": "user-1", "name": "Aviad"},
        "updatedBy": {"id": "user-1", "name": "Aviad"},
        "project": {"id": "project-1", "name": "Platform Reboot"},
    }


@pytest.mark.asyncio
async def test_incremental_pull_smoke_materializes_all_changed_entities(
    tmp_path: Path,
) -> None:
    """INVARIANT: incremental pull writes complete markdown for all changed entity types."""
    (tmp_path / ".sync").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sync" / "state.json").write_text(
        json.dumps({"last_sync": LAST_SYNC_TS})
    )

    with (
        patch(
            "issueclaw.commands.pull.LinearClient.fetch_teams",
            new=AsyncMock(return_value=[TEAM_ENG]),
        ),
        patch(
            "issueclaw.commands.pull.LinearClient.fetch_issues",
            new=AsyncMock(return_value=[_issue_payload()]),
        ),
        patch(
            "issueclaw.commands.pull.LinearClient.fetch_projects",
            new=AsyncMock(return_value=[_project_payload()]),
        ),
        patch(
            "issueclaw.commands.pull.LinearClient.fetch_initiatives",
            new=AsyncMock(return_value=[_initiative_payload()]),
        ),
        patch(
            "issueclaw.commands.pull.LinearClient.fetch_documents",
            new=AsyncMock(return_value=[_document_payload()]),
        ),
    ):
        stats = await _run_pull(
            api_key="test-key",
            repo_dir=tmp_path,
            teams_filter=["ENG"],
            log=lambda _: None,
            show_progress=False,
        )

    assert stats == {"issues": 1, "projects": 1, "initiatives": 1, "documents": 1}

    issue_file = (
        tmp_path / "linear" / "teams" / "ENG" / "issues" / "ENG-42-incremental-smoke.md"
    )
    project_file = tmp_path / "linear" / "projects" / "platform-reboot" / "_project.md"
    initiative_file = tmp_path / "linear" / "initiatives" / "2026-platform-drive.md"
    document_file = tmp_path / "linear" / "documents" / "incremental-sync-playbook.md"

    assert issue_file.exists()
    assert project_file.exists()
    assert initiative_file.exists()
    assert document_file.exists()

    issue_text = issue_file.read_text()
    assert "# Comments" in issue_text
    assert "Edited comment body" in issue_text

    assert "Incremental update." in project_file.read_text()
    assert "Initiative content" in initiative_file.read_text()
    assert "Fresh content from incremental sync." in document_file.read_text()
