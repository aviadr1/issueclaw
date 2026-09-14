"""Preview must exercise the real renderer without claiming or publishing work."""

from unittest.mock import AsyncMock, patch

import pytest

from issueclaw import inbox_preview
from issueclaw.commands import apply_webhook as webhook
from issueclaw.entity_changes import apply_changes, prepare_entity
from issueclaw.inbox_contract import Payload, WorkItem
from issueclaw.sync_state import SyncState
from tests.test_apply_webhook import _make_issue_api_response


@pytest.mark.asyncio
async def test_preview_reports_changes_and_noops_without_modifying_mirror(tmp_path):
    raw = _make_issue_api_response()
    item = WorkItem(
        key=f"org/Issue/{raw['id']}",
        generation=1,
        payload=Payload(
            type="Issue",
            action="update",
            data={"id": raw["id"]},
            createdAt="2026-09-14T00:00:00Z",
        ),
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.return_value = raw
    with patch.object(webhook, "LinearClient", return_value=client):
        result = await inbox_preview.preview([item], tmp_path, "unused", limit=1)
        assert result[0].outcome == "changes"
        assert list(tmp_path.iterdir()) == []
        apply_changes(
            tmp_path,
            await prepare_entity(item.payload.model_dump(), "unused", tmp_path),
        )
        before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        result = await inbox_preview.preview([item], tmp_path, "unused", limit=1)
        assert result[0].outcome == "noop"
    assert before == {
        str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }


@pytest.mark.asyncio
async def test_preview_bounds_source_reads_and_detects_conflicts_without_linear(
    tmp_path,
):
    state = SyncState(tmp_path)
    for name in ("old", "new"):
        path = tmp_path / f"linear/{name}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(name)
        state.add_mapping(f"linear/{name}.md", "conflict")
    state.save()
    items = [
        WorkItem(
            key=f"org/Issue/{id}",
            generation=1,
            payload=Payload(
                type="Issue",
                action="update",
                data={"id": id},
                createdAt="2026-09-14T00:00:00Z",
            ),
        )
        for id in ("conflict", "unselected")
    ]
    with patch.object(webhook, "LinearClient") as client:
        results = await inbox_preview.preview(items, tmp_path, "unused", limit=1)
        assert [r.outcome for r in results] == ["identity_conflict"]
        client.assert_not_called()
    with pytest.raises(ValueError):
        await inbox_preview.preview(items, tmp_path, "unused", limit=26)


@pytest.mark.parametrize(
    "error,expected", [(TimeoutError, "timeout"), (RuntimeError, "error")]
)
@pytest.mark.asyncio
async def test_preview_classifies_source_failures_without_disclosing_content(
    tmp_path, error, expected
):
    item = WorkItem(
        key="org/Issue/source",
        generation=1,
        payload=Payload(
            type="Issue",
            action="update",
            data={"id": "source"},
            createdAt="2026-09-14T00:00:00Z",
        ),
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.side_effect = error("sensitive upstream response")
    with patch.object(webhook, "LinearClient", return_value=client):
        results = await inbox_preview.preview([item], tmp_path, "unused", limit=1)
    assert results[0].outcome == expected
    assert "sensitive" not in repr(results)
    assert list(tmp_path.iterdir()) == []
