from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.linear_client import LinearClient


@pytest.fixture
def client():
    return LinearClient(api_key="test-key")


def test_client_init(client):
    """INVARIANT: Client initializes with API key and correct endpoint."""
    assert client.api_key == "test-key"
    assert "linear.app" in client.api_url


@pytest.mark.asyncio
async def test_fetch_teams(client):
    """INVARIANT: fetch_teams returns list of team dicts with key field."""
    mock_response = {
        "data": {
            "teams": {
                "nodes": [
                    {"id": "uuid-1", "name": "Engineering", "key": "ENG"},
                    {"id": "uuid-2", "name": "AI", "key": "AI"},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        teams = await client.fetch_teams()
        assert len(teams) == 2
        assert teams[0]["name"] == "Engineering"
        assert teams[1]["key"] == "AI"


@pytest.mark.asyncio
async def test_fetch_issues_paginated(client):
    """INVARIANT: fetch_issues handles pagination, concatenating all pages."""
    page1 = {
        "data": {
            "team": {
                "issues": {
                    "nodes": [{"id": "1", "identifier": "AI-1"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"},
                }
            }
        }
    }
    page2 = {
        "data": {
            "team": {
                "issues": {
                    "nodes": [{"id": "2", "identifier": "AI-2"}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, side_effect=[page1, page2]
    ):
        issues = await client.fetch_issues(team_id="uuid")
        assert len(issues) == 2
        assert issues[0]["identifier"] == "AI-1"
        assert issues[1]["identifier"] == "AI-2"


@pytest.mark.asyncio
async def test_fetch_comments(client):
    """INVARIANT: fetch_comments returns comments for an issue."""
    mock_response = {
        "data": {
            "issue": {
                "comments": {
                    "nodes": [
                        {
                            "id": "c1",
                            "body": "Hello",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "updatedAt": "2026-01-01T00:00:00Z",
                            "user": {"id": "u1", "name": "Aviad"},
                        },
                    ]
                }
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        comments = await client.fetch_comments(issue_id="issue-uuid")
        assert len(comments) == 1
        assert comments[0]["body"] == "Hello"


@pytest.mark.asyncio
async def test_fetch_projects(client):
    """INVARIANT: fetch_projects returns list of project dicts."""
    mock_response = {
        "data": {
            "projects": {
                "nodes": [
                    {"id": "p1", "name": "Project A", "slugId": "project-a"},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        projects = await client.fetch_projects()
        assert len(projects) == 1
        assert projects[0]["name"] == "Project A"


@pytest.mark.asyncio
async def test_fetch_documents(client):
    """INVARIANT: fetch_documents returns list of document dicts."""
    mock_response = {
        "data": {
            "documents": {
                "nodes": [
                    {"id": "d1", "title": "Doc A", "content": "# Hello"},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        docs = await client.fetch_documents()
        assert len(docs) == 1
        assert docs[0]["title"] == "Doc A"


@pytest.mark.asyncio
async def test_fetch_initiatives(client):
    """INVARIANT: fetch_initiatives returns list of initiative dicts."""
    mock_response = {
        "data": {
            "initiatives": {
                "nodes": [
                    {"id": "i1", "name": "Q1 Roadmap"},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        initiatives = await client.fetch_initiatives()
        assert len(initiatives) == 1
        assert initiatives[0]["name"] == "Q1 Roadmap"


@pytest.mark.asyncio
async def test_fetch_team_states(client):
    """INVARIANT: fetch_team_states returns workflow states for a team."""
    mock_response = {
        "data": {
            "team": {
                "states": {
                    "nodes": [
                        {"id": "state-1", "name": "Todo", "type": "backlog"},
                        {"id": "state-2", "name": "In Progress", "type": "started"},
                        {"id": "state-3", "name": "Done", "type": "completed"},
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        states = await client.fetch_team_states(team_id="team-uuid")
        assert len(states) == 3
        assert states[0]["name"] == "Todo"
        assert states[2]["name"] == "Done"


@pytest.mark.asyncio
async def test_fetch_users(client):
    """INVARIANT: fetch_users returns workspace users with id and name."""
    mock_response = {
        "data": {
            "users": {
                "nodes": [
                    {
                        "id": "user-1",
                        "name": "Aviad Rozenhek",
                        "email": "aviad@test.com",
                    },
                    {"id": "user-2", "name": "Oz Shaked", "email": "oz@test.com"},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }
    with patch.object(
        client, "_graphql", new_callable=AsyncMock, return_value=mock_response
    ):
        users = await client.fetch_users()
        assert len(users) == 2
        assert users[0]["name"] == "Aviad Rozenhek"
