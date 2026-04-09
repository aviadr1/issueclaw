"""Regression tests for resilient document creation flows."""

from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands import create as create_mod
from issueclaw.linear_client import LinearClient
from issueclaw.main import cli
from issueclaw.sync_state import SyncState


@pytest.mark.asyncio
async def test_linear_client_create_document_handles_null_data():
    """INVARIANT: create_document returns {} when GraphQL responds with data=null."""
    client = LinearClient(api_key="test-key")
    with patch.object(
        client,
        "_graphql",
        new_callable=AsyncMock,
        return_value={"data": None, "errors": [{"message": "forbidden"}]},
    ):
        doc = await client.create_document("Doc title", {"content": "body"})

    assert doc == {}


@pytest.mark.asyncio
async def test_linear_client_create_document_handles_graphql_errors_payload():
    """INVARIANT: GraphQL errors payload does not crash create_document parsing."""
    client = LinearClient(api_key="test-key")
    with patch.object(
        client,
        "_graphql",
        new_callable=AsyncMock,
        return_value={
            "errors": [{"message": "Forbidden"}],
            "data": {"documentCreate": None},
        },
    ):
        doc = await client.create_document("Doc title", {"content": "body"})

    assert doc == {}


def test_create_document_cli_fails_cleanly_when_linear_returns_no_document(tmp_path):
    """INVARIANT: CLI create document exits with a clear error (no AttributeError)."""
    mock_client = AsyncMock()
    mock_client.fetch_teams.return_value = [{"id": "team-ai", "key": "AI"}]
    mock_client.create_document.return_value = {}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(create_mod, "LinearClient", return_value=mock_client):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "create",
                "document",
                "--api-key",
                "test-key",
                "--repo-dir",
                str(tmp_path),
                "--title",
                "Smoke doc",
                "--team",
                "AI",
            ],
            input="body from stdin\n",
        )

    assert result.exit_code != 0
    assert "Linear API did not return a document ID." in result.output
    assert "AttributeError" not in result.output


@pytest.mark.asyncio
async def test_create_document_writes_file_and_id_map(tmp_path):
    """INVARIANT: successful create document writes canonical file and id-map mapping."""
    mock_client = AsyncMock()
    mock_client.fetch_teams.return_value = [{"id": "team-ai", "key": "AI"}]
    mock_client.create_document.return_value = {
        "id": "doc-uuid-1",
        "title": "A Great Doc",
        "slugId": "a-great-doc",
        "url": "https://linear.app/test/document/a-great-doc",
        "createdAt": "2026-04-09T00:00:00Z",
        "updatedAt": "2026-04-09T00:00:00Z",
        "creator": {"name": "Aviad"},
    }
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(create_mod, "LinearClient", return_value=mock_client):
        result = await create_mod._create_document(
            "test-key",
            tmp_path,
            "A Great Doc",
            "Document body",
            None,
            "AI",
        )

    assert result["id"] == "doc-uuid-1"
    assert result["file"] == "linear/documents/a-great-doc.md"

    doc_file = tmp_path / "linear" / "documents" / "a-great-doc.md"
    assert doc_file.exists()
    content = doc_file.read_text()
    assert "id: doc-uuid-1" in content
    assert "# A Great Doc" in content
    assert "Document body" in content

    state = SyncState(tmp_path)
    state.load()
    assert state.get_uuid("linear/documents/a-great-doc.md") == "doc-uuid-1"


@pytest.mark.asyncio
async def test_create_document_requires_scope_team_or_project(tmp_path):
    """INVARIANT: create document requires exactly one scope: team or project."""
    with pytest.raises(create_mod.click.UsageError):
        await create_mod._create_document(
            "test-key",
            tmp_path,
            "Scoped Doc",
            "Body",
            None,
            None,
        )


@pytest.mark.asyncio
async def test_create_document_resolves_team_scope(tmp_path):
    """INVARIANT: --team resolves to teamId for documentCreate mutation."""
    mock_client = AsyncMock()
    mock_client.fetch_teams.return_value = [{"id": "team-dsg", "key": "DSG"}]
    mock_client.create_document.return_value = {
        "id": "doc-uuid-2",
        "title": "Design Doc",
        "slugId": "design-doc",
        "url": "https://linear.app/test/document/design-doc",
        "createdAt": "2026-04-09T00:00:00Z",
        "updatedAt": "2026-04-09T00:00:00Z",
        "creator": {"name": "Aviad"},
    }
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(create_mod, "LinearClient", return_value=mock_client):
        await create_mod._create_document(
            "test-key",
            tmp_path,
            "Design Doc",
            "Body",
            None,
            "DSG",
        )

    mock_client.create_document.assert_called_once()
    called_fields = mock_client.create_document.call_args[0][1]
    assert called_fields["teamId"] == "team-dsg"
