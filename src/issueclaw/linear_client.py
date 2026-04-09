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

    async def _graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict:
        """Execute a GraphQL query against the Linear API with retry."""
        client = await self._ensure_client()
        last_response: httpx.Response | None = None
        for attempt in range(5):
            response = await client.post(
                self.api_url,
                json={"query": query, "variables": variables or {}},
            )
            last_response = response
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
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from Linear: {response.text[:500]}",
                    request=response.request,
                    response=response,
                )
            return response.json()
        if last_response is None:
            raise RuntimeError("No response received from Linear API")
        raise httpx.HTTPStatusError(
            f"{last_response.status_code} from Linear: {last_response.text[:500]}",
            request=last_response.request,
            response=last_response,
        )

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

    async def fetch_issues(
        self,
        team_id: str,
        include_comments: bool = True,
        updated_after: str | None = None,
    ) -> list[dict]:
        """Fetch all issues for a team, paginated.

        When include_comments=True, comments are fetched inline (up to 50 per issue),
        avoiding the need for separate comment API calls.

        When updated_after is provided (ISO 8601), only issues updated at or after
        that timestamp are returned, making incremental syncs cheap.
        """
        comments_fragment = (
            """
                        comments(first: 50) {
                            nodes {
                                id body createdAt updatedAt
                                user { id name email }
                            }
                        }"""
            if include_comments
            else ""
        )

        if updated_after:
            filter_arg = ", filter: { updatedAt: { gte: $updatedAfter } }"
            updated_after_var = ", $updatedAfter: DateTimeOrDuration"
        else:
            filter_arg = ""
            updated_after_var = ""

        query = f"""
        query TeamIssues($teamId: String!, $after: String{updated_after_var}) {{
            team(id: $teamId) {{
                issues(first: 50, after: $after{filter_arg}) {{
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
        variables: dict = {"teamId": team_id}
        if updated_after:
            variables["updatedAfter"] = updated_after
        return await self._paginate(query, ["team", "issues"], variables)

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
        return (
            result.get("data", {}).get("issue", {}).get("comments", {}).get("nodes", [])
        )

    async def fetch_projects(self, updated_after: str | None = None) -> list[dict]:
        """Fetch all projects in the workspace.

        Uses smaller page size (5) due to query complexity from nested connections
        (milestones, updates, members, initiatives, documents).

        When updated_after is provided (ISO 8601), only projects updated at or after
        that timestamp are returned.
        """
        if updated_after:
            filter_arg = ", filter: { updatedAt: { gte: $updatedAfter } }"
            updated_after_var = ", $updatedAfter: DateTimeOrDuration"
        else:
            filter_arg = ""
            updated_after_var = ""

        query = f"""
        query Projects($after: String{updated_after_var}) {{
            projects(first: 5, after: $after{filter_arg}) {{
                nodes {{
                    id name slugId description content
                    priority health progress scope
                    url createdAt updatedAt
                    startDate targetDate
                    status {{ id name color type }}
                    lead {{ id name email }}
                    teams {{ nodes {{ id name key }} }}
                    members {{ nodes {{ id name }} }}
                    labels {{ nodes {{ id name }} }}
                    projectMilestones {{
                        nodes {{ id name description targetDate status progress }}
                    }}
                    projectUpdates(first: 10) {{
                        nodes {{ id body health createdAt user {{ id name }} }}
                    }}
                    initiatives {{ nodes {{ id name }} }}
                    documents {{ nodes {{ id title }} }}
                }}
                pageInfo {{ hasNextPage endCursor }}
            }}
        }}
        """
        variables: dict = {}
        if updated_after:
            variables["updatedAfter"] = updated_after
        return await self._paginate(query, ["projects"], variables or None)

    async def fetch_initiatives(self, updated_after: str | None = None) -> list[dict]:
        """Fetch all initiatives in the workspace.

        When updated_after is provided (ISO 8601), only initiatives updated at or
        after that timestamp are returned.
        """
        if updated_after:
            filter_arg = ", filter: { updatedAt: { gte: $updatedAfter } }"
            updated_after_var = ", $updatedAfter: DateTimeOrDuration"
        else:
            filter_arg = ""
            updated_after_var = ""

        query = f"""
        query Initiatives($after: String{updated_after_var}) {{
            initiatives(first: 50, after: $after{filter_arg}) {{
                nodes {{
                    id name description content
                    status health
                    targetDate createdAt updatedAt
                    url
                    owner {{ id name email }}
                    projects {{ nodes {{ id name }} }}
                }}
                pageInfo {{ hasNextPage endCursor }}
            }}
        }}
        """
        variables: dict = {}
        if updated_after:
            variables["updatedAfter"] = updated_after
        return await self._paginate(query, ["initiatives"], variables or None)

    async def fetch_documents(self, updated_after: str | None = None) -> list[dict]:
        """Fetch all documents in the workspace.

        When updated_after is provided (ISO 8601), only documents updated at or
        after that timestamp are returned.
        """
        if updated_after:
            filter_arg = ", filter: { updatedAt: { gte: $updatedAfter } }"
            updated_after_var = ", $updatedAfter: DateTimeOrDuration"
        else:
            filter_arg = ""
            updated_after_var = ""

        query = f"""
        query Documents($after: String{updated_after_var}) {{
            documents(first: 50, after: $after{filter_arg}) {{
                nodes {{
                    id title content slugId icon color
                    url createdAt updatedAt
                    creator {{ id name }}
                    updatedBy {{ id name }}
                    project {{ id name }}
                }}
                pageInfo {{ hasNextPage endCursor }}
            }}
        }}
        """
        variables: dict = {}
        if updated_after:
            variables["updatedAfter"] = updated_after
        return await self._paginate(query, ["documents"], variables or None)

    async def fetch_team_states(self, team_id: str) -> list[dict]:
        """Fetch all workflow states for a team."""
        query = """
        query TeamStates($teamId: String!, $after: String) {
            team(id: $teamId) {
                states(first: 50, after: $after) {
                    nodes {
                        id name type color position
                    }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }
        """
        return await self._paginate(query, ["team", "states"], {"teamId": team_id})

    async def fetch_users(self) -> list[dict]:
        """Fetch all users in the workspace."""
        query = """
        query Users($after: String) {
            users(first: 50, after: $after) {
                nodes {
                    id name email displayName active
                }
                pageInfo { hasNextPage endCursor }
            }
        }
        """
        return await self._paginate(query, ["users"])

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
        result = await self._graphql(
            query, {"input": {"issueId": issue_id, "body": body}}
        )
        return result.get("data", {}).get("commentCreate", {}).get("comment", {})

    async def fetch_labels_for_team(self, team_id: str) -> list[dict]:
        """Fetch all issue labels available for a team."""
        query = """
        query TeamLabels($teamId: String!, $after: String) {
            team(id: $teamId) {
                labels(first: 50, after: $after) {
                    nodes { id name }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }
        """
        return await self._paginate(query, ["team", "labels"], {"teamId": team_id})

    async def create_issue(self, team_id: str, fields: dict) -> dict:
        """Create a new issue in Linear. Returns {id, identifier, title, url}."""
        query = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue { id identifier title url createdAt updatedAt state { name } assignee { name } }
            }
        }
        """
        result = await self._graphql(query, {"input": {"teamId": team_id, **fields}})
        return result.get("data", {}).get("issueCreate", {}).get("issue", {})

    async def create_project(
        self, name: str, team_ids: list[str], fields: dict
    ) -> dict:
        """Create a new project in Linear. Returns {id, name, slugId, url}."""
        query = """
        mutation CreateProject($input: ProjectCreateInput!) {
            projectCreate(input: $input) {
                success
                project { id name slugId url createdAt updatedAt }
            }
        }
        """
        result = await self._graphql(
            query, {"input": {"name": name, "teamIds": team_ids, **fields}}
        )
        return result.get("data", {}).get("projectCreate", {}).get("project", {})

    async def create_initiative(self, name: str, fields: dict) -> dict:
        """Create a new initiative in Linear. Returns {id, name, url}."""
        query = """
        mutation CreateInitiative($input: InitiativeCreateInput!) {
            initiativeCreate(input: $input) {
                success
                initiative { id name url createdAt updatedAt }
            }
        }
        """
        result = await self._graphql(query, {"input": {"name": name, **fields}})
        return result.get("data", {}).get("initiativeCreate", {}).get("initiative", {})

    async def update_document(self, document_id: str, fields: dict) -> dict:
        """Update a document's fields in Linear."""
        query = """
        mutation UpdateDocument($documentId: String!, $input: DocumentUpdateInput!) {
            documentUpdate(id: $documentId, input: $input) {
                success
                document { id title slugId url }
            }
        }
        """
        result = await self._graphql(
            query, {"documentId": document_id, "input": fields}
        )
        return result.get("data", {}).get("documentUpdate", {}).get("document", {})

    async def create_document(self, title: str, fields: dict) -> dict:
        """Create a new document in Linear. Returns {id, title, slugId, url}."""
        query = """
        mutation CreateDocument($input: DocumentCreateInput!) {
            documentCreate(input: $input) {
                success
                document { id title slugId url createdAt updatedAt creator { name } }
            }
        }
        """
        result = await self._graphql(query, {"input": {"title": title, **fields}})
        return result.get("data", {}).get("documentCreate", {}).get("document", {})

    async def create_project_update(
        self, project_id: str, body: str, health: str = "onTrack"
    ) -> dict:
        """Create a status update on a project in Linear."""
        query = """
        mutation CreateProjectUpdate($input: ProjectUpdateCreateInput!) {
            projectUpdateCreate(input: $input) {
                success
                projectUpdate { id body health }
            }
        }
        """
        result = await self._graphql(
            query, {"input": {"projectId": project_id, "body": body, "health": health}}
        )
        return (
            result.get("data", {})
            .get("projectUpdateCreate", {})
            .get("projectUpdate", {})
        )
