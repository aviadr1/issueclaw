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
from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands.pull import _run_pull
from issueclaw.linear_client import LinearClient

LAST_SYNC_TS = "2026-03-29T10:00:00Z"
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


def _pull_stack(
    mock_fetch_issues=None,
    mock_fetch_projects=None,
    mock_fetch_initiatives=None,
    mock_fetch_documents=None,
) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(
        patch.object(
            LinearClient, "fetch_teams", new=AsyncMock(return_value=[TEAM_ENG])
        )
    )
    stack.enter_context(
        patch.object(
            LinearClient,
            "fetch_issues",
            new=mock_fetch_issues or AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch.object(
            LinearClient,
            "fetch_projects",
            new=mock_fetch_projects or AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch.object(
            LinearClient,
            "fetch_initiatives",
            new=mock_fetch_initiatives or AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch.object(
            LinearClient,
            "fetch_documents",
            new=mock_fetch_documents or AsyncMock(return_value=[]),
        )
    )
    return stack


async def _run(repo, **mocks):
    await _run_pull(
        api_key="test-key",
        repo_dir=repo,
        teams_filter=["ENG"],
        log=lambda _: None,
        show_progress=False,
    )


class TestPullPassesUpdatedAfterFromLastSync:
    """
    _run_pull must read state.last_sync and pass it as updated_after to every
    LinearClient fetch call. Without this, Linear returns all entities on every
    run regardless of whether they changed.
    """

    @pytest.mark.asyncio
    async def test_fetch_issues_receives_updated_after(
        self, repo_with_last_sync: Path
    ) -> None:
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
    async def test_fetch_projects_receives_updated_after(
        self, repo_with_last_sync: Path
    ) -> None:
        """
        INVARIANT: fetch_projects is called with updated_after when last_sync is set.
        """
        mock_fetch_projects = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_projects=mock_fetch_projects):
            await _run(repo_with_last_sync)

        mock_fetch_projects.assert_called_once_with(updated_after=LAST_SYNC_TS)

    @pytest.mark.asyncio
    async def test_fetch_initiatives_receives_updated_after(
        self, repo_with_last_sync: Path
    ) -> None:
        """
        INVARIANT: fetch_initiatives is called with updated_after when last_sync is set.
        """
        mock_fetch_initiatives = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_initiatives=mock_fetch_initiatives):
            await _run(repo_with_last_sync)

        mock_fetch_initiatives.assert_called_once_with(updated_after=LAST_SYNC_TS)

    @pytest.mark.asyncio
    async def test_fetch_documents_receives_updated_after(
        self, repo_with_last_sync: Path
    ) -> None:
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
    async def test_fetch_issues_has_no_updated_after_on_first_sync(
        self, repo: Path
    ) -> None:
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
    async def test_fetch_projects_has_no_updated_after_on_first_sync(
        self, repo: Path
    ) -> None:
        mock_fetch_projects = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_projects=mock_fetch_projects):
            await _run(repo)

        mock_fetch_projects.assert_called_once_with(updated_after=None)

    @pytest.mark.asyncio
    async def test_fetch_initiatives_has_no_updated_after_on_first_sync(
        self, repo: Path
    ) -> None:
        mock_fetch_initiatives = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_initiatives=mock_fetch_initiatives):
            await _run(repo)

        mock_fetch_initiatives.assert_called_once_with(updated_after=None)

    @pytest.mark.asyncio
    async def test_fetch_documents_has_no_updated_after_on_first_sync(
        self, repo: Path
    ) -> None:
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

        async def mock_graphql(
            self_arg, query: str, variables: dict | None = None
        ) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {
                "data": {
                    "team": {
                        "issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}
                    }
                }
            }

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_issues("team-id", updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"], (
            "updatedAfter must be passed as a GraphQL variable"
        )
        assert captured["variables"]["updatedAfter"] == LAST_SYNC_TS, (
            "The variable must carry the exact last_sync timestamp"
        )
        assert "updatedAt" in captured["query"], (
            "The GraphQL query must reference the updatedAt field in a filter"
        )
        assert "gte" in captured["query"], (
            "The filter must use gte (greater-than-or-equal) to include the boundary timestamp"
        )

    @pytest.mark.asyncio
    async def test_fetch_issues_graphql_query_has_no_filter_when_updated_after_is_none(
        self,
    ) -> None:
        """
        INVARIANT: When updated_after is None, the GraphQL query must NOT include
        an updatedAt filter — so all issues are returned on the initial sync.
        """
        captured: dict = {}

        async def mock_graphql(
            self_arg, query: str, variables: dict | None = None
        ) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {
                "data": {
                    "team": {
                        "issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}
                    }
                }
            }

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_issues("team-id", updated_after=None)

        assert "updatedAfter" not in captured.get("variables", {}), (
            "No updatedAfter variable should be sent when updated_after is None"
        )

    @pytest.mark.asyncio
    async def test_fetch_projects_graphql_query_contains_updated_at_filter(
        self,
    ) -> None:
        """
        INVARIANT: fetch_projects with updated_after sends a filtered GraphQL query.
        """
        captured: dict = {}

        async def mock_graphql(
            self_arg, query: str, variables: dict | None = None
        ) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {
                "data": {"projects": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
            }

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_projects(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert captured["variables"]["updatedAfter"] == LAST_SYNC_TS
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]

    @pytest.mark.asyncio
    async def test_fetch_initiatives_graphql_query_contains_updated_at_filter(
        self,
    ) -> None:
        captured: dict = {}

        async def mock_graphql(
            self_arg, query: str, variables: dict | None = None
        ) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {
                "data": {
                    "initiatives": {"nodes": [], "pageInfo": {"hasNextPage": False}}
                }
            }

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_initiatives(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]

    @pytest.mark.asyncio
    async def test_fetch_documents_graphql_query_contains_updated_at_filter(
        self,
    ) -> None:
        captured: dict = {}

        async def mock_graphql(
            self_arg, query: str, variables: dict | None = None
        ) -> dict:
            captured["query"] = query
            captured["variables"] = dict(variables or {})
            return {
                "data": {"documents": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
            }

        with patch.object(LinearClient, "_graphql", new=mock_graphql):
            async with LinearClient(api_key="test-key") as client:
                await client.fetch_documents(updated_after=LAST_SYNC_TS)

        assert "updatedAfter" in captured["variables"]
        assert "updatedAt" in captured["query"]
        assert "gte" in captured["query"]


class TestLastSyncRecordedAtRunStart:
    """
    last_sync must be recorded at the START of _run_pull, not the end.

    WHY THIS IS A SILENT DATA-LOSS BUG:
      _run_pull processes teams sequentially. A sync run for 8 teams takes
      several minutes. An issue updated at T_start+2min (after ENG was already
      processed, while MOB is still being fetched) is NOT fetched in this run —
      it arrived after its team's turn. But if last_sync is recorded as T_end
      (current behavior), the NEXT incremental sync uses updated_after=T_end.
      Since the issue has updatedAt=T_start+2min < T_end, Linear won't return it.
      It is permanently invisible until a manual full re-sync.

    THE FIX:
      Record sync_start = datetime.now() ONCE before any fetching begins.
      Use sync_start for all state.set_last_sync() calls throughout the run.
      Now updated_after=T_start on the next run, and T_start+2min > T_start,
      so the issue IS returned. No data is ever silently dropped.
    """

    @pytest.mark.asyncio
    async def test_last_sync_is_set_to_run_start_not_end(self, repo: Path) -> None:
        """
        INVARIANT: After _run_pull completes, last_sync must equal the time
        datetime.now() was called BEFORE fetching started, not after.

        We control datetime.now() to return T_START on the first call and
        T_END on every subsequent call. If last_sync == T_START, the run
        captured the start time. If last_sync == T_END, it captured the end
        time and the mid-run gap is invisible to the next incremental sync.
        """
        import issueclaw.commands.pull as pull_mod
        from datetime import datetime as real_datetime, timezone
        from unittest.mock import MagicMock

        T_START = real_datetime(2026, 3, 30, 10, 0, 0, tzinfo=timezone.utc)
        T_END = real_datetime(2026, 3, 30, 10, 5, 0, tzinfo=timezone.utc)

        call_count = 0

        def controlled_now(tz=None):
            nonlocal call_count
            call_count += 1
            return T_START if call_count == 1 else T_END

        mock_dt = MagicMock()
        mock_dt.now.side_effect = controlled_now

        with patch.object(pull_mod, "datetime", mock_dt):
            with _pull_stack():
                await _run_pull(
                    api_key="test-key",
                    repo_dir=repo,
                    teams_filter=["ENG"],
                    log=lambda _: None,
                    show_progress=False,
                )

        from issueclaw.sync_state import SyncState

        state = SyncState(repo)
        state.load()

        expected = T_START.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert state.last_sync == expected, (
            f"last_sync must be the run START time {expected!r}, "
            f"not the run END time {T_END.strftime('%Y-%m-%dT%H:%M:%SZ')!r}. "
            "Issues updated during the sync run would otherwise be missed by "
            "the next incremental sync."
        )

    @pytest.mark.asyncio
    async def test_issue_updated_during_sync_run_is_caught_by_next_incremental_sync(
        self, repo: Path
    ) -> None:
        """
        INVARIANT: An issue updated at T_mid (where T_start < T_mid < T_end of a
        sync run) must be fetched by the NEXT incremental sync.

        If last_sync = T_end: T_mid < T_end → updated_after=T_end → issue missed.
        If last_sync = T_start: T_mid > T_start → updated_after=T_start → issue caught.

        This test directly verifies the data-safety consequence of the bug.
        """
        import issueclaw.commands.pull as pull_mod
        from datetime import datetime as real_datetime, timezone
        from unittest.mock import MagicMock
        from issueclaw.sync_state import SyncState

        T_START = real_datetime(2026, 3, 30, 10, 0, 0, tzinfo=timezone.utc)
        T_MID = real_datetime(2026, 3, 30, 10, 2, 30, tzinfo=timezone.utc)
        T_END = real_datetime(2026, 3, 30, 10, 5, 0, tzinfo=timezone.utc)

        # Simulate the first sync run: datetime.now() returns T_START then T_END.
        first_run_count = 0

        def first_run_now(tz=None):
            nonlocal first_run_count
            first_run_count += 1
            return T_START if first_run_count == 1 else T_END

        mock_dt_first = MagicMock()
        mock_dt_first.now.side_effect = first_run_now

        with patch.object(pull_mod, "datetime", mock_dt_first):
            with _pull_stack():
                await _run_pull(
                    api_key="test-key",
                    repo_dir=repo,
                    teams_filter=["ENG"],
                    log=lambda _: None,
                    show_progress=False,
                )

        # Record what last_sync was saved as after the first run.
        state = SyncState(repo)
        state.load()
        saved_last_sync = state.last_sync

        # Now run the second (incremental) sync. The issue was updated at T_MID —
        # during the first sync run, after ENG was already processed.
        mock_fetch_issues_2 = AsyncMock(return_value=[])
        with _pull_stack(mock_fetch_issues=mock_fetch_issues_2):
            await _run_pull(
                api_key="test-key",
                repo_dir=repo,
                teams_filter=["ENG"],
                log=lambda _: None,
                show_progress=False,
            )

        # The second run must use updated_after=saved_last_sync.
        # For the issue (updatedAt=T_MID) to be fetched, saved_last_sync <= T_MID.
        # With bug (last_sync=T_END): T_END > T_MID → issue is invisible.
        # With fix (last_sync=T_START): T_START < T_MID → issue is fetched.
        mock_fetch_issues_2.assert_called_once_with(
            TEAM_ENG["id"],
            include_comments=True,
            updated_after=saved_last_sync,
        )
        assert saved_last_sync is not None
        assert saved_last_sync <= T_MID.isoformat(), (
            f"last_sync={saved_last_sync!r} must be <= T_MID={T_MID.isoformat()!r} "
            "so the issue updated during the sync run is caught by the next incremental sync. "
            "Fix: record last_sync = datetime.now() at run START, not at run END."
        )
