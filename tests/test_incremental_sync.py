"""
Incremental pull tests.

WHY THIS MATTERS:
  issueclaw pull fetches all teams × all issues × all projects × all documents.
  8 teams with hundreds of issues = hundreds of Linear API calls per sync run.
  Running every 15 minutes = thousands of calls/hour, rate-limit risk, CI waste.

THE FIX (two parts):
  Part A — LinearClient: fetch_issues/fetch_projects/fetch_initiatives/fetch_documents
    accept updated_after: str | None. When set, the GraphQL query adds a
    filter: { updatedAt: { gte: $updatedAfter } } so Linear only returns
    entities changed in the window.

  Part B — _run_pull: reads state.last_sync from .sync/state.json and passes
    it as updated_after to every fetch_* call. The first sync (no last_sync)
    still fetches everything to bootstrap. Each subsequent sync only fetches
    what changed since the last run.

These tests are written FIRST. They fail until the issueclaw implementation lands.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

import pytest

from issueclaw.commands.pull import _run_pull
from issueclaw.linear_client import LinearClient

LAST_SYNC_TS = "2026-03-29T10:00:00.000Z"
TEAM_ENG = {"id": "team-eng", "key": "ENG", "name": "Engineering"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".sync").mkdir()
    (tmp_path / "linear" / "teams" / "ENG" / "issues").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def repo_with_last_sync(repo: Path) -> Path:
    """Repo that has already run a sync — last_sync is recorded in state."""
    (repo / ".sync" / "state.json").write_text(json.dumps({"last_sync": LAST_SYNC_TS}))
    return repo


def _pull_stack(mock_fetch_issues=None, mock_fetch_projects=None,
                mock_fetch_initiatives=None, mock_fetch_documents=None) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch.object(LinearClient, "fetch_teams",
        new=AsyncMock(return_value=[TEAM_ENG])))
    stack.enter_context(patch.object(LinearClient, "fetch_issues",
        new=mock_fetch_issues or AsyncMock(return_value=[])))
    stack.enter_context(patch.object(LinearClient, "fetch_projects",
        new=mock_fetch_projects or AsyncMock(return_value=[])))
    stack.enter_context(patch.object(LinearClient, "fetch_initiatives",
        new=mock_fetch_initiatives or AsyncMock(return_value=[])))
    stack.enter_context(patch.object(LinearClient, "fetch_documents",
        new=mock_fetch_documents or AsyncMock(return_value=[])))
    return stack


async def _run(repo, **mocks):
    await _run_pull(api_key="test-key", repo_dir=repo,
                    teams_filter=["ENG"], log=lambda _: None, show_progress=False)


class TestPullPassesUpdatedAfterFromLastSync:
    """
    _run_pull must read state.last_sync and pass it as updated_after to every
    LinearClient fetch call. Without this, Linear returns all entities on every
    run regardless of whether they changed.
    """

    @pytest.mark.asyncio
    async def test_fetch_issues_receives_updated_after(self, repo_with_last_sync: Path) -> None:
        """
        INVARIANT: When last_sync is recorded, fetch_issues is called with
        updated_after=<last_sync> so Linear only returns recently-changed issues.
        """
        mock_fetch_issues = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_issues=mock_fetch_issues):
            await _run(repo_with_last_sync)

        mock_fetch_issues.assert_called_once_with(
            TEAM_ENG["id"], include_comments=True, updated_after=LAST_SYNC_TS
        )

    @pytest.mark.asyncio
    async def test_fetch_projects_receives_updated_after(self, repo_with_last_sync: Path) -> None:
        """
        INVARIANT: fetch_projects is called with updated_after when last_sync is set.
        """
        mock_fetch_projects = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_projects=mock_fetch_projects):
            await _run(repo_with_last_sync)

        mock_fetch_projects.assert_called_once_with(updated_after=LAST_SYNC_TS)

    @pytest.mark.asyncio
    async def test_fetch_initiatives_receives_updated_after(self, repo_with_last_sync: Path) -> None:
        """
        INVARIANT: fetch_initiatives is called with updated_after when last_sync is set.
        """
        mock_fetch_initiatives = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_initiatives=mock_fetch_initiatives):
            await _run(repo_with_last_sync)

        mock_fetch_initiatives.assert_called_once_with(updated_after=LAST_SYNC_TS)

    @pytest.mark.asyncio
    async def test_fetch_documents_receives_updated_after(self, repo_with_last_sync: Path) -> None:
        """
        INVARIANT: fetch_documents is called with updated_after when last_sync is set.
        """
        mock_fetch_documents = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_documents=mock_fetch_documents):
            await _run(repo_with_last_sync)

        mock_fetch_documents.assert_called_once_with(updated_after=LAST_SYNC_TS)


class TestFirstSyncFetchesEverything:
    """
    When no last_sync exists (first-ever sync, or state wiped), _run_pull must
    fetch all entities with no filter to bootstrap the repo from scratch.
    Regression: the incremental-pull fix must not break the initial full sync.
    """

    @pytest.mark.asyncio
    async def test_fetch_issues_has_no_updated_after_on_first_sync(self, repo: Path) -> None:
        """
        INVARIANT: Without last_sync, fetch_issues is called with no updated_after
        (or updated_after=None) so all issues are returned.
        """
        mock_fetch_issues = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_issues=mock_fetch_issues):
            await _run(repo)

        mock_fetch_issues.assert_called_once_with(
            TEAM_ENG["id"], include_comments=True, updated_after=None
        )

    @pytest.mark.asyncio
    async def test_fetch_projects_has_no_updated_after_on_first_sync(self, repo: Path) -> None:
        mock_fetch_projects = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_projects=mock_fetch_projects):
            await _run(repo)

        mock_fetch_projects.assert_called_once_with(updated_after=None)

    @pytest.mark.asyncio
    async def test_fetch_initiatives_has_no_updated_after_on_first_sync(self, repo: Path) -> None:
        mock_fetch_initiatives = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_initiatives=mock_fetch_initiatives):
            await _run(repo)

        mock_fetch_initiatives.assert_called_once_with(updated_after=None)

    @pytest.mark.asyncio
    async def test_fetch_documents_has_no_updated_after_on_first_sync(self, repo: Path) -> None:
        mock_fetch_documents = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_documents=mock_fetch_documents):
            await _run(repo)

        mock_fetch_documents.assert_called_once_with(updated_after=None)


class TestGraphQLFilterIsActuallySentToLinear:
    """
    Mocking fetch_issues is not enough — we must verify that when updated_after
    is provided, the actual GraphQL query sent to Linear contains the filter.
    If the filter is missing from the query, Linear returns everything anyway
    and we get no benefit despite the code looking correct at the Python level.
    """

    @pytest.mark.asyncio
    async def test_fetch_issues_graphql_query_contains_updated_at_filter(self) -> None:
        """
        INVARIANT: fetch_issues with updated_after sends a GraphQL query that
        includes a updatedAt filter, and passes the timestamp as a variable.
        """
        captured: dict = {}

        async def mock_graphql(self_arg, query: str, variables: dict | None = None) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {"data": {"team": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}}

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_issues("team-id", updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"], \
            "updatedAfter must be passed as a GraphQL variable"
        assert captured["variables"]["updatedAfter"] == LAST_SYNC_TS, \
            "The variable must carry the exact last_sync timestamp"
        assert "updatedAt" in captured["query"], \
            "The GraphQL query must reference the updatedAt field in a filter"
        assert "gte" in captured["query"], \
            "The filter must use gte (greater-than-or-equal) to include the boundary timestamp"

    @pytest.mark.asyncio
    async def test_fetch_issues_graphql_query_has_no_filter_when_updated_after_is_none(self) -> None:
        """
        INVARIANT: When updated_after is None, the GraphQL query must NOT include
        an updatedAt filter — so all issues are returned on the initial sync.
        """
        captured: dict = {}

        async def mock_graphql(self_arg, query: str, variables: dict | None = None) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {"data": {"team": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}}

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_issues("team-id", updated_after=None)

        assert "updatedAfter" not in captured.get("variables", {}), \
            "No updatedAfter variable should be sent when updated_after is None"

    @pytest.mark.asyncio
    async def test_fetch_projects_graphql_query_contains_updated_at_filter(self) -> None:
        """
        INVARIANT: fetch_projects with updated_after sends a filtered GraphQL query.
        """
        captured: dict = {}

        async def mock_graphql(self_arg, query: str, variables: dict | None = None) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {"data": {"projects": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_projects(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert captured["variables"]["updatedAfter"] == LAST_SYNC_TS
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]

    @pytest.mark.asyncio
    async def test_fetch_initiatives_graphql_query_contains_updated_at_filter(self) -> None:
        captured: dict = {}

        async def mock_graphql(self_arg, query: str, variables: dict | None = None) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {"data": {"initiatives": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_initiatives(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]

    @pytest.mark.asyncio
    async def test_fetch_documents_graphql_query_contains_updated_at_filter(self) -> None:
        captured: dict = {}

        async def mock_graphql(self_arg, query: str, variables: dict | None = None) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {"data": {"documents": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_documents(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]
