"""Linear GraphQL API client."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class LinearClient:
    """Async client for the Linear GraphQL API."""

    api_url = "https://api.linear.app/graphql"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client for connection reuse."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> LinearClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        """Execute a GraphQL query against the Linear API with retry."""
        client = await self._ensure_client()
        for attempt in range(5):
            response = await client.post(
                self.api_url,
                json={"query": query, "variables": variables or {}},
            )
            # Linear returns 400 for rate limits with RATELIMITED in body
            if response.status_code == 429 or (
                response.status_code == 400 and "RATELIMITED" in response.text
            ):
                retry_after = int(response.headers.get("retry-after", 10))
                await asyncio.sleep(max(retry_after, 5))
                continue
            if response.status_code >= 500 and attempt < 4:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()
        return response.json()

    async def _paginate(
        self, query: str, path: list[str], variables: dict[str, Any] | None = None
    ) -> list[dict]:
        """Paginate through a GraphQL connection, returning all nodes."""
        all_nodes: list[dict] = []
        cursor: str | None = None
        variables = dict(variables or {})

        for _ in range(100):  # safety limit
            variables["after"] = cursor
            result = await self._graphql(query, variables)

            # Navigate to the connection object
            data = result.get("data", {})
            for key in path:
                data = data.get(key, {})

            nodes = data.get("nodes", [])
            all_nodes.extend(nodes)

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break
            cursor = page_info.get("endCursor")

        return all_nodes

    async def fetch_teams(self) -> list[dict]:
        """Fetch all teams in the workspace."""
        query = """
        query Teams($after: String) {
            teams(first: 50, after: $after) {
                nodes {
                    id name key icon
                    createdAt updatedAt
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        return await self._paginate(query, ["teams"])

    async def fetch_issues(self, team_id: str, include_comments: bool = True) -> list[dict]:
        """Fetch all issues for a team, paginated.

        When include_comments=True, comments are fetched inline (up to 50 per issue),
        avoiding the need for separate comment API calls.
        """
        comments_fragment = """
                        comments(first: 50) {
                            nodes {
                                id body createdAt updatedAt
                                user { id name email }
                            }
                        }""" if include_comments else ""

        query = f"""
        query TeamIssues($teamId: String!, $after: String) {{
            team(id: $teamId) {{
                issues(first: 50, after: $after) {{
                    nodes {{
                        id identifier title description
                        priority priorityLabel
                        url createdAt updatedAt dueDate
                        estimate
                        startedAt completedAt canceledAt
                        state {{ name }}
                        assignee {{ id name email }}
                        labels {{ nodes {{ name }} }}
                        project {{ id name }}
                        projectMilestone {{ id name }}
                        parent {{ id identifier title }}
                        cycle {{ id name }}{comments_fragment}
                    }}
                    pageInfo {{ hasNextPage endCursor }}
                }}
            }}
        }}
        """
        return await self._paginate(query, ["team", "issues"], {"teamId": team_id})

    async def fetch_issue(self, issue_id: str) -> dict:
        """Fetch a single issue by ID with full data including team and comments."""
        query = """
        query Issue($issueId: String!) {
            issue(id: $issueId) {
                id identifier title description
                priority priorityLabel
                url createdAt updatedAt dueDate
                estimate
                startedAt completedAt canceledAt
                state { name }
                assignee { id name email }
                labels { nodes { name } }
                project { id name }
                projectMilestone { id name }
                parent { id identifier title }
                cycle { id name }
                team { id key name }
                comments(first: 50) {
                    nodes {
                        id body createdAt updatedAt
                        user { id name email }
                    }
                }
            }
        }
        """
        result = await self._graphql(query, {"issueId": issue_id})
        return result.get("data", {}).get("issue", {})

    async def fetch_project(self, project_id: str) -> dict:
        """Fetch a single project by ID with full data."""
        query = """
        query Project($projectId: String!) {
            project(id: $projectId) {
                id name slugId description content
                priority health progress scope
                url createdAt updatedAt
                startDate targetDate
                status { id name color type }
                lead { id name email }
                teams { nodes { id name key } }
                members { nodes { id name } }
                labels { nodes { id name } }
                projectMilestones {
                    nodes { id name description targetDate status progress }
                }
                projectUpdates(first: 10) {
                    nodes { id body health createdAt user { id name } }
                }
                initiatives { nodes { id name } }
                documents { nodes { id title } }
            }
        }
        """
        result = await self._graphql(query, {"projectId": project_id})
        return result.get("data", {}).get("project", {})

    async def fetch_initiative(self, initiative_id: str) -> dict:
        """Fetch a single initiative by ID."""
        query = """
        query Initiative($initiativeId: String!) {
            initiative(id: $initiativeId) {
                id name description content
                status health
                targetDate createdAt updatedAt
                url
                owner { id name email }
                projects { nodes { id name } }
            }
        }
        """
        result = await self._graphql(query, {"initiativeId": initiative_id})
        return result.get("data", {}).get("initiative", {})

    async def fetch_document(self, document_id: str) -> dict:
        """Fetch a single document by ID."""
        query = """
        query Document($documentId: String!) {
            document(id: $documentId) {
                id title content slugId icon color
                url createdAt updatedAt
                creator { id name }
                updatedBy { id name }
                project { id name }
            }
        }
        """
        result = await self._graphql(query, {"documentId": document_id})
        return result.get("data", {}).get("document", {})

    async def fetch_comments(self, issue_id: str) -> list[dict]:
        """Fetch all comments for an issue."""
        query = """
        query IssueComments($issueId: String!) {
            issue(id: $issueId) {
                comments(first: 100) {
                    nodes {
                        id body createdAt updatedAt
                        user { id name email }
                    }
                }
            }
        }
        """
        result = await self._graphql(query, {"issueId": issue_id})
        return result.get("data", {}).get("issue", {}).get("comments", {}).get("nodes", [])

    async def fetch_projects(self) -> list[dict]:
        """Fetch all projects in the workspace.

        Uses smaller page size (5) due to query complexity from nested connections
        (milestones, updates, members, initiatives, documents).
        """
        query = """
        query Projects($after: String) {
            projects(first: 5, after: $after) {
                nodes {
                    id name slugId description content
                    priority health progress scope
                    url createdAt updatedAt
                    startDate targetDate
                    status { id name color type }
                    lead { id name email }
                    teams { nodes { id name key } }
                    members { nodes { id name } }
                    labels { nodes { id name } }
                    projectMilestones {
                        nodes { id name description targetDate status progress }
                    }
                    projectUpdates(first: 10) {
                        nodes { id body health createdAt user { id name } }
                    }
                    initiatives { nodes { id name } }
                    documents { nodes { id title } }
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        return await self._paginate(query, ["projects"])

    async def fetch_initiatives(self) -> list[dict]:
        """Fetch all initiatives in the workspace."""
        query = """
        query Initiatives($after: String) {
            initiatives(first: 50, after: $after) {
                nodes {
                    id name description content
                    status health
                    targetDate createdAt updatedAt
                    url
                    owner { id name email }
                    projects { nodes { id name } }
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        return await self._paginate(query, ["initiatives"])

    async def fetch_documents(self) -> list[dict]:
        """Fetch all documents in the workspace."""
        query = """
        query Documents($after: String) {
            documents(first: 50, after: $after) {
                nodes {
                    id title content slugId icon color
                    url createdAt updatedAt
                    creator { id name }
                    updatedBy { id name }
                    project { id name }
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        return await self._paginate(query, ["documents"])

    # Mutation methods for push sync

    async def update_issue(self, issue_id: str, fields: dict) -> dict:
        """Update an issue's fields in Linear."""
        query = """
        mutation UpdateIssue($issueId: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $issueId, input: $input) {
                success
                issue { id identifier title }
            }
        }
        """
        result = await self._graphql(query, {"issueId": issue_id, "input": fields})
        return result.get("data", {}).get("issueUpdate", {}).get("issue", {})

    async def archive_issue(self, issue_id: str) -> dict:
        """Archive an issue in Linear."""
        query = """
        mutation ArchiveIssue($issueId: String!) {
            issueArchive(id: $issueId) {
                success
            }
        }
        """
        result = await self._graphql(query, {"issueId": issue_id})
        return result.get("data", {}).get("issueArchive", {})

    async def create_comment(self, issue_id: str, body: str) -> dict:
        """Create a comment on an issue in Linear."""
        query = """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment { id body }
            }
        }
        """
        result = await self._graphql(query, {"input": {"issueId": issue_id, "body": body}})
        return result.get("data", {}).get("commentCreate", {}).get("comment", {})
