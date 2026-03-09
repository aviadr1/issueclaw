# issueclaw Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a bidirectional sync tool that mirrors Linear data as markdown files in a GitHub repository, using git diffs as the change detection mechanism and GitHub Actions as the compute layer.

**Architecture:**
- **Two separate repos:**
  - `aviadr1/issueclaw` — the tool's source code (this repo). Contains NO Linear data.
  - `gigaverse-app/linear-git` — the target repo where Linear data is mirrored as `.md` files. This is the GitHub master. GitHub Actions workflows and the `.sync/` metadata live here.
- Linear syncs to/from the **target repo** via GitHub Actions workflows.
- Developers clone the target repo, edit `.md` files, push. Normal git.
- `issueclaw` is installed as a CLI tool (`uv tool install issueclaw`) and operates on the target repo (passed via `--repo` flag or cwd).

**Tech Stack:** Python 3.12, Click (CLI), Pydantic (models), httpx (Linear GraphQL API), PyYAML (frontmatter), Rich (output), uv (package manager), pytest (testing).

**Key Principles:**
- This repo (issueclaw) is code-only. No Linear data here.
- The target GitHub repo is the source of truth. Linear is a view into it.
- Developers use standard git workflows (clone, edit, push, pull).
- `issueclaw sync` operates on a local clone of the target repo.

---

## Linear API Response Shapes (verified against live API)

These shapes reflect what we actually fetch via GraphQL. Key learning: the GraphQL API
returns nested objects (not flat strings), and has a 10000 complexity limit per query.

### Team
```json
{"id": "uuid", "name": "Engineering", "key": "ENG", "icon": "Robot", "createdAt": "ISO", "updatedAt": "ISO"}
```

### Issue (fetched with inline comments, 50/page)
```json
{
  "id": "uuid", "identifier": "ENG-6148", "title": "...", "description": "markdown...",
  "priority": 4, "priorityLabel": "Low",
  "url": "https://linear.app/...",
  "createdAt": "ISO", "updatedAt": "ISO", "dueDate": null,
  "startedAt": "ISO|null", "completedAt": "ISO|null", "canceledAt": "ISO|null",
  "estimate": null,
  "state": {"name": "Todo"},
  "assignee": {"id": "uuid", "name": "Name", "email": "..."},
  "labels": {"nodes": [{"name": "Backend"}]},
  "project": {"id": "uuid", "name": "Project Name"},
  "projectMilestone": {"id": "uuid", "name": "MVP"},
  "parent": {"id": "uuid", "identifier": "ENG-100", "title": "Parent Issue"},
  "cycle": {"id": "uuid", "name": "Sprint 5"},
  "comments": {"nodes": [{"id": "uuid", "body": "...", "createdAt": "ISO", "user": {"id": "uuid", "name": "..."}}]}
}
```

### Project (fetched 5/page due to complexity)
```json
{
  "id": "uuid", "name": "Metrics Platform", "slugId": "7bb22805ba90",
  "description": "Short description", "content": "# Rich markdown body...",
  "priority": 2, "health": "onTrack", "progress": 0.75, "scope": 36,
  "url": "...", "createdAt": "ISO", "updatedAt": "ISO",
  "startDate": "2026-02-12", "targetDate": null,
  "status": {"id": "uuid", "name": "Ready for Dev", "color": "#4cb782", "type": "started"},
  "lead": {"id": "uuid", "name": "...", "email": "..."},
  "teams": {"nodes": [{"id": "uuid", "name": "Web", "key": "WEB"}]},
  "members": {"nodes": [{"id": "uuid", "name": "Aviad"}]},
  "labels": {"nodes": [{"id": "uuid", "name": "Metrics"}]},
  "projectMilestones": {"nodes": [{"id": "uuid", "name": "MVP", "description": "...", "targetDate": "...", "status": "done", "progress": 1.0}]},
  "projectUpdates": {"nodes": [{"id": "uuid", "body": "markdown...", "health": "onTrack", "createdAt": "ISO", "user": {"id": "uuid", "name": "..."}}]},
  "initiatives": {"nodes": [{"id": "uuid", "name": "Community metrics"}]},
  "documents": {"nodes": [{"id": "uuid", "title": "Architecture Design"}]}
}
```

### Initiative (fetched with linked projects)
```json
{
  "id": "uuid", "name": "Community metrics",
  "description": "Short desc", "content": "# Rich markdown body...",
  "status": "Active", "health": "atRisk",
  "targetDate": "2026-06-30", "url": "...",
  "createdAt": "ISO", "updatedAt": "ISO",
  "owner": {"id": "uuid", "name": "...", "email": "..."},
  "projects": {"nodes": [{"id": "uuid", "name": "Metrics Platform"}]}
}
```

### Document
```json
{
  "id": "uuid", "title": "...", "content": "markdown...", "slugId": "abc123",
  "url": "...", "createdAt": "ISO", "updatedAt": "ISO",
  "creator": {"id": "uuid", "name": "..."}, "updatedBy": {"id": "uuid", "name": "..."},
  "project": {"id": "uuid", "name": "..."}
}
```

### Comment (fetched inline with issues)
```json
{
  "id": "uuid", "body": "markdown...",
  "createdAt": "ISO", "updatedAt": "ISO",
  "user": {"id": "uuid", "name": "Name", "email": "..."}
}
```

### API Quirks Discovered
- **Complexity limit**: 10000 per query. Rich project queries need page size 5 (not 50).
- **Rate limiting**: Returns HTTP 400 (not 429) with "RATELIMITED" in body. Check body text.
- **Connection reuse**: Must use persistent httpx.AsyncClient; creating per-request hits 3000+ TCP connections.
- **Inline comments**: `comments(first: 50)` on issues avoids N+1 API calls (3300+ → ~70 calls).
- **Project slugs**: `slugId` is a hex hash. Use `_slugify(name)` for readable file paths.
- **Content vs description**: Projects and initiatives have both. `content` is the rich body; `description` is a short summary. Prefer `content` when present.

---

## Phase 1: Read-Only Pull (Linear to Git)

Phase 1 delivers: `issueclaw sync` command that pulls all Linear data into `.md` files in the GitHub repo. Zero risk (read-only).

### Task 1: Pydantic Models for Linear Entities

**Files:**
- Create: `src/issueclaw/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from issueclaw.models import LinearIssue, LinearComment, LinearProject, LinearDocument

def test_issue_from_api_response():
    """INVARIANT: Issue model correctly parses Linear API response."""
    data = {
        "id": "ed4db4cb-393b-4104-a04b-6ac67073a145",
        "identifier": "ENG-6148",
        "title": "Remove community v1",
        "description": "The migration is complete.",
        "priority": {"value": 4, "name": "Low"},
        "url": "https://linear.app/gigaverse/issue/ENG-6148",
        "createdAt": "2025-11-27T16:25:38.608Z",
        "updatedAt": "2026-03-09T16:25:22.937Z",
        "dueDate": None,
        "status": "Todo",
        "labels": ["Backend", "TechDebt"],
        "assignee": "Marek Chabiera",
        "assigneeId": "c4baaac3-uuid",
        "team": "Engineering",
        "teamId": "215fad93-uuid",
    }
    issue = LinearIssue.from_api(data)
    assert issue.id == "ed4db4cb-393b-4104-a04b-6ac67073a145"
    assert issue.identifier == "ENG-6148"
    assert issue.title == "Remove community v1"
    assert issue.status == "Todo"
    assert issue.priority == 4
    assert issue.priority_name == "Low"
    assert issue.labels == ["Backend", "TechDebt"]
    assert issue.team_key is None  # not in basic response, resolved later

def test_comment_from_api_response():
    """INVARIANT: Comment model correctly parses Linear API response."""
    data = {
        "id": "0cc38243-uuid",
        "body": "Can we plan this?",
        "createdAt": "2025-12-09T15:13:34.879Z",
        "updatedAt": "2025-12-10T09:54:47.586Z",
        "author": {"id": "17c35488-uuid", "name": "Abhishek Balaji"},
    }
    comment = LinearComment.from_api(data)
    assert comment.id == "0cc38243-uuid"
    assert comment.body == "Can we plan this?"
    assert comment.author_name == "Abhishek Balaji"

def test_project_from_api_response():
    """INVARIANT: Project model correctly parses Linear API response."""
    data = {
        "id": "2b5c3067-uuid",
        "name": "Coupons Backend",
        "description": "Coupons architecture...",
        "url": "https://linear.app/gigaverse/project/coupons",
        "createdAt": "2026-03-02T12:59:11.476Z",
        "updatedAt": "2026-03-03T17:49:27.105Z",
        "startDate": None,
        "targetDate": None,
        "labels": [],
        "lead": {"id": "c4baaac3-uuid", "name": "Marek Chabiera"},
        "status": {"id": "bfac304f-uuid", "name": "Backlog"},
        "teams": [{"id": "84b57c2b-uuid", "name": "Backend", "key": "BE"}],
        "milestones": [],
    }
    project = LinearProject.from_api(data)
    assert project.id == "2b5c3067-uuid"
    assert project.name == "Coupons Backend"
    assert project.status == "Backlog"
    assert project.lead_name == "Marek Chabiera"

def test_document_from_api_response():
    """INVARIANT: Document model correctly parses Linear API response."""
    data = {
        "id": "68120669-uuid",
        "title": "Pre-Live Deep Dive",
        "content": "# Meeting Notes",
        "slugId": "3bf0aaa880bb",
        "url": "https://linear.app/gigaverse/document/...",
        "createdAt": "2026-03-03T16:56:08.060Z",
        "updatedAt": "2026-03-04T15:12:31.640Z",
        "creator": {"id": "e144e8bf-uuid", "name": "Jakub Drozdek"},
        "project": {"id": "b4d10c92-uuid", "name": "Improve Pre Live"},
    }
    doc = LinearDocument.from_api(data)
    assert doc.id == "68120669-uuid"
    assert doc.title == "Pre-Live Deep Dive"
    assert doc.slug_id == "3bf0aaa880bb"
    assert doc.creator_name == "Jakub Drozdek"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError - models module doesn't exist yet

**Step 3: Write minimal implementation**

Create `src/issueclaw/models.py` with Pydantic models:
- `LinearIssue` - id, identifier, title, description, status, priority, priority_name, assignee, labels, team, team_key, project, milestone, estimate, due_date, created, updated, url, comments list
- `LinearComment` - id, body, author_name, author_id, created, updated
- `LinearProject` - id, name, slug, description, status, lead_name, priority, start_date, target_date, labels, url, created, updated, teams, milestones
- `LinearDocument` - id, title, content, slug_id, url, creator_name, created, updated, project_name
- Each with `@classmethod from_api(cls, data: dict) -> Self` that maps API response shape to our model

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**
```bash
git add src/issueclaw/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for Linear entities"
```

---

### Task 2: Path Convention Utilities

**Files:**
- Create: `src/issueclaw/paths.py`
- Test: `tests/test_paths.py`

**Step 1: Write the failing test**

```python
# tests/test_paths.py
from issueclaw.paths import entity_path, parse_entity_path, slugify

def test_issue_path():
    """INVARIANT: Issue path follows linear/teams/{KEY}/issues/{ID}.md convention."""
    assert entity_path("issue", team_key="AI", identifier="AI-123") == "linear/teams/AI/issues/AI-123.md"

def test_project_path():
    assert entity_path("project", slug="chapter-detection") == "linear/projects/chapter-detection/_project.md"

def test_milestone_path():
    assert entity_path("milestone", project_slug="chapter-detection", name="mvp") == "linear/projects/chapter-detection/milestones/mvp.md"

def test_initiative_path():
    assert entity_path("initiative", name="Q1 2026 Roadmap") == "linear/initiatives/q1-2026-roadmap.md"

def test_document_path():
    assert entity_path("document", title="Architecture Overview", slug_id="abc123") == "linear/documents/architecture-overview.md"

def test_parse_issue_path():
    """INVARIANT: Parsing a path returns entity type and identifiers."""
    result = parse_entity_path("linear/teams/AI/issues/AI-123.md")
    assert result["type"] == "issue"
    assert result["team_key"] == "AI"
    assert result["identifier"] == "AI-123"

def test_parse_project_path():
    result = parse_entity_path("linear/projects/chapter-detection/_project.md")
    assert result["type"] == "project"
    assert result["slug"] == "chapter-detection"

def test_slugify():
    assert slugify("Q1 2026 Roadmap") == "q1-2026-roadmap"
    assert slugify("Architecture Overview") == "architecture-overview"
```

**Step 2:** Run: `uv run pytest tests/test_paths.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/paths.py` with `entity_path()`, `parse_entity_path()`, `slugify()`.

**Step 4:** Run: `uv run pytest tests/test_paths.py -v` — Expected: PASS

**Step 5:** Commit: `git commit -m "feat: add path convention utilities"`

---

### Task 3: Markdown Renderer

**Files:**
- Create: `src/issueclaw/render.py`
- Test: `tests/test_render.py`

**Step 1: Write the failing test**

```python
# tests/test_render.py
import yaml
from issueclaw.render import render_issue, render_project, render_document
from issueclaw.models import LinearIssue, LinearComment, LinearProject, LinearDocument

def test_render_issue_frontmatter():
    """INVARIANT: Rendered issue has correct YAML frontmatter and body."""
    issue = LinearIssue(
        id="uuid-123", identifier="AI-123", title="Implement chapter detection",
        description="Build chapter detection.", status="In Progress",
        priority=2, priority_name="High", assignee="aviad@gigaverse.ai",
        labels=["feature", "ai"], team="AI", project="chapter-detection",
        created="2026-01-15T10:00:00Z", updated="2026-03-01T14:30:00Z",
        url="https://linear.app/gigaverse/issue/AI-123",
    )
    md = render_issue(issue)
    assert md.startswith("---\n")
    # Parse frontmatter
    parts = md.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["id"] == "uuid-123"
    assert fm["identifier"] == "AI-123"
    assert fm["status"] == "In Progress"
    assert fm["labels"] == ["feature", "ai"]
    # Body
    assert "Build chapter detection." in parts[2]

def test_render_issue_with_comments():
    """INVARIANT: Comments are embedded under ## Comments section."""
    comments = [
        LinearComment(id="c1", body="Started working.", author_name="aviad@gigaverse.ai",
                      created="2026-02-15T09:00:00Z", updated="2026-02-15T09:00:00Z"),
        LinearComment(id="c2", body="Looks good!", author_name="john@gigaverse.ai",
                      created="2026-02-20T11:00:00Z", updated="2026-02-20T11:00:00Z"),
    ]
    issue = LinearIssue(
        id="uuid-123", identifier="AI-123", title="Test",
        description="Body.", status="Todo", priority=3, priority_name="Normal",
        created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test", comments=comments,
    )
    md = render_issue(issue)
    assert "## Comments" in md
    assert "### aviad@gigaverse.ai - 2026-02-15T09:00:00Z" in md
    assert "<!-- comment-id: c1 -->" in md
    assert "Started working." in md
    assert "### john@gigaverse.ai - 2026-02-20T11:00:00Z" in md

def test_render_project():
    """INVARIANT: Project renders with correct frontmatter."""
    project = LinearProject(
        id="uuid-proj", name="Chapter Detection", slug="chapter-detection",
        description="Build chapter detection.", status="started",
        lead_name="aviad@gigaverse.ai", priority=2,
        start_date="2026-01-01", target_date="2026-06-30",
        labels=["ai-features"],
        url="https://linear.app/gigaverse/project/chapter-detection",
        created="2026-01-01T00:00:00Z", updated="2026-03-01T00:00:00Z",
    )
    md = render_project(project)
    parts = md.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["name"] == "Chapter Detection"
    assert fm["slug"] == "chapter-detection"
    assert fm["status"] == "started"

def test_render_document():
    """INVARIANT: Document renders title and content."""
    doc = LinearDocument(
        id="uuid-doc", title="Architecture Overview", content="# Overview\nDetails here.",
        slug_id="abc123", url="https://linear.app/...",
        creator_name="Jakub",
        created="2026-01-01T00:00:00Z", updated="2026-02-01T00:00:00Z",
    )
    md = render_document(doc)
    parts = md.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    assert fm["title"] == "Architecture Overview"
    assert "# Overview" in parts[2]
```

**Step 2:** Run: `uv run pytest tests/test_render.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/render.py`:
- `render_issue(issue, comments=None) -> str` — YAML frontmatter + body + comments section
- `render_project(project) -> str`
- `render_initiative(initiative) -> str`
- `render_document(document) -> str`
- Helper: `_render_frontmatter(fields: dict) -> str` — dumps YAML between `---` markers, skipping None values
- Helper: `_render_comments(comments: list[LinearComment]) -> str`

**Step 4:** Run: `uv run pytest tests/test_render.py -v` — Expected: PASS

**Step 5:** Commit: `git commit -m "feat: add markdown renderer for Linear entities"`

---

### Task 4: Markdown Parser

**Files:**
- Create: `src/issueclaw/parse.py`
- Test: `tests/test_parse.py`

**Step 1: Write the failing test**

```python
# tests/test_parse.py
from issueclaw.parse import parse_markdown

def test_parse_issue_with_comments():
    """INVARIANT: Parser extracts frontmatter, body, and comments from .md files."""
    md = '''---
id: "uuid-123"
identifier: "AI-123"
title: "Test issue"
status: "In Progress"
priority: 2
labels:
  - "feature"
---

Issue description here.

## Comments

### aviad@gigaverse.ai - 2026-02-15T09:00:00Z
<!-- comment-id: c1-uuid -->

Started working on this.

### john@gigaverse.ai - 2026-02-20T11:00:00Z
<!-- comment-id: c2-uuid -->

Looks good!
'''
    result = parse_markdown(md)
    assert result.frontmatter["id"] == "uuid-123"
    assert result.frontmatter["status"] == "In Progress"
    assert result.frontmatter["labels"] == ["feature"]
    assert "Issue description here." in result.body
    assert len(result.comments) == 2
    assert result.comments[0].id == "c1-uuid"
    assert result.comments[0].author == "aviad@gigaverse.ai"
    assert "Started working" in result.comments[0].body
    assert result.comments[1].id == "c2-uuid"

def test_parse_issue_without_comments():
    """INVARIANT: Parser works when no comments section exists."""
    md = '''---
id: "uuid-456"
title: "No comments"
---

Just a body.
'''
    result = parse_markdown(md)
    assert result.frontmatter["id"] == "uuid-456"
    assert "Just a body." in result.body
    assert result.comments == []

def test_roundtrip_issue():
    """INVARIANT: render -> parse -> render produces identical output."""
    from issueclaw.models import LinearIssue, LinearComment
    from issueclaw.render import render_issue
    issue = LinearIssue(
        id="uuid", identifier="AI-1", title="Test", description="Body text.",
        status="Todo", priority=3, priority_name="Normal",
        created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test",
        comments=[LinearComment(id="c1", body="Hello.", author_name="user@test.com",
                                created="2026-01-02T00:00:00Z", updated="2026-01-02T00:00:00Z")],
    )
    md1 = render_issue(issue)
    parsed = parse_markdown(md1)
    # Verify roundtrip preserves data
    assert parsed.frontmatter["identifier"] == "AI-1"
    assert "Body text." in parsed.body
    assert len(parsed.comments) == 1
    assert parsed.comments[0].id == "c1"
```

**Step 2:** Run: `uv run pytest tests/test_parse.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/parse.py`:
- `ParsedMarkdown` dataclass with `frontmatter: dict`, `body: str`, `comments: list[ParsedComment]`
- `ParsedComment` dataclass with `id: str`, `author: str`, `timestamp: str`, `body: str`
- `parse_markdown(content: str) -> ParsedMarkdown` — splits on `---`, parses YAML, extracts body and comments

**Step 4:** Run: `uv run pytest tests/test_parse.py -v` — Expected: PASS

**Step 5:** Commit: `git commit -m "feat: add markdown parser with frontmatter and comment extraction"`

---

### Task 5: Sync State Management (id-map)

**Files:**
- Create: `src/issueclaw/sync_state.py`
- Test: `tests/test_sync_state.py`

**Step 1: Write the failing test**

```python
# tests/test_sync_state.py
import json
from pathlib import Path
from issueclaw.sync_state import SyncState

def test_id_map_add_and_lookup(tmp_path):
    """INVARIANT: id-map maps file paths to Linear UUIDs bidirectionally."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    assert state.get_uuid("linear/teams/AI/issues/AI-123.md") == "uuid-123"
    assert state.get_path("uuid-123") == "linear/teams/AI/issues/AI-123.md"

def test_id_map_persistence(tmp_path):
    """INVARIANT: id-map persists to disk and survives reload."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    state.save()
    # Reload
    state2 = SyncState(tmp_path)
    state2.load()
    assert state2.get_uuid("linear/teams/AI/issues/AI-123.md") == "uuid-123"

def test_id_map_remove(tmp_path):
    """INVARIANT: Removing a mapping clears both directions."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    state.remove_mapping("linear/teams/AI/issues/AI-123.md")
    assert state.get_uuid("linear/teams/AI/issues/AI-123.md") is None
    assert state.get_path("uuid-123") is None

def test_state_json_timestamps(tmp_path):
    """INVARIANT: state.json tracks last sync timestamp."""
    state = SyncState(tmp_path)
    state.set_last_sync("2026-03-09T12:00:00Z")
    state.save()
    state2 = SyncState(tmp_path)
    state2.load()
    assert state2.last_sync == "2026-03-09T12:00:00Z"
```

**Step 2:** Run: `uv run pytest tests/test_sync_state.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/sync_state.py` with `SyncState` class managing `.sync/id-map.json` and `.sync/state.json`.

**Step 4:** Run: `uv run pytest tests/test_sync_state.py -v` — Expected: PASS

**Step 5:** Commit: `git commit -m "feat: add sync state management for id-map and timestamps"`

---

### Task 6: Linear GraphQL API Client

**Files:**
- Create: `src/issueclaw/linear_client.py`
- Test: `tests/test_linear_client.py`

**Step 1: Write the failing test**

```python
# tests/test_linear_client.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx
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
    """INVARIANT: fetch_teams returns list of team dicts."""
    mock_response = {
        "data": {
            "teams": {
                "nodes": [
                    {"id": "uuid-1", "name": "Engineering", "key": "ENG"},
                    {"id": "uuid-2", "name": "AI", "key": "AI"},
                ],
                "pageInfo": {"hasNextPage": False}
            }
        }
    }
    with patch.object(client, '_graphql', new_callable=AsyncMock, return_value=mock_response):
        teams = await client.fetch_teams()
        assert len(teams) == 2
        assert teams[0]["name"] == "Engineering"
        assert teams[1]["key"] == "AI"

@pytest.mark.asyncio
async def test_fetch_issues_paginated(client):
    """INVARIANT: fetch_issues handles pagination correctly."""
    page1 = {
        "data": {"issues": {"nodes": [{"id": "1", "identifier": "AI-1"}],
                             "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"}}}
    }
    page2 = {
        "data": {"issues": {"nodes": [{"id": "2", "identifier": "AI-2"}],
                             "pageInfo": {"hasNextPage": False}}}
    }
    with patch.object(client, '_graphql', new_callable=AsyncMock, side_effect=[page1, page2]):
        issues = await client.fetch_issues(team_id="uuid")
        assert len(issues) == 2
        assert issues[0]["identifier"] == "AI-1"
        assert issues[1]["identifier"] == "AI-2"
```

**Step 2:** Run: `uv run pytest tests/test_linear_client.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/linear_client.py`:
- `LinearClient` class with httpx async client
- `_graphql(query, variables)` - sends GraphQL request to `https://api.linear.app/graphql`
- `fetch_teams()` - paginated team fetch
- `fetch_issues(team_id, after=None)` - paginated issue fetch with all fields
- `fetch_comments(issue_id)` - fetch comments for an issue
- `fetch_projects()` - paginated project fetch
- `fetch_initiatives()` - paginated initiative fetch
- `fetch_documents()` - paginated document fetch

**Step 4:** Run: `uv run pytest tests/test_linear_client.py -v` — Expected: PASS

**Step 5:** Commit: `git commit -m "feat: add Linear GraphQL API client with pagination"`

---

### Task 7: Initial Sync Command

**Files:**
- Create: `src/issueclaw/commands/initial_sync.py`
- Modify: `src/issueclaw/main.py` (register command)
- Test: `tests/test_initial_sync.py`

**Step 1: Write the failing test**

```python
# tests/test_initial_sync.py
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from click.testing import CliRunner
from issueclaw.main import cli

@pytest.fixture
def runner():
    return CliRunner()

def test_initial_sync_creates_issue_files(runner, tmp_path):
    """INVARIANT: Initial sync creates .md files for all issues in specified teams."""
    mock_client = MagicMock()
    mock_client.fetch_teams = AsyncMock(return_value=[
        {"id": "team-uuid", "name": "AI", "key": "AI"}
    ])
    mock_client.fetch_issues = AsyncMock(return_value=[
        {
            "id": "issue-uuid", "identifier": "AI-1", "title": "Test issue",
            "description": "Body", "priority": {"value": 3, "name": "Normal"},
            "status": "Todo", "labels": [], "assignee": None, "team": "AI",
            "teamId": "team-uuid", "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z", "url": "https://linear.app/test",
            "dueDate": None,
        }
    ])
    mock_client.fetch_comments = AsyncMock(return_value=[])
    mock_client.fetch_projects = AsyncMock(return_value=[])
    mock_client.fetch_initiatives = AsyncMock(return_value=[])
    mock_client.fetch_documents = AsyncMock(return_value=[])

    with patch('issueclaw.commands.initial_sync.LinearClient', return_value=mock_client):
        result = runner.invoke(cli, ["sync", "--teams", "AI", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    issue_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1.md"
    assert issue_file.exists()
    content = issue_file.read_text()
    assert "AI-1" in content
    assert "Test issue" in content

    # Check id-map was created
    id_map = tmp_path / ".sync" / "id-map.json"
    assert id_map.exists()
    mapping = json.loads(id_map.read_text())
    assert "linear/teams/AI/issues/AI-1.md" in mapping
```

**Step 2:** Run: `uv run pytest tests/test_initial_sync.py -v` — Expected: FAIL

**Step 3:** Create `src/issueclaw/commands/initial_sync.py`:
- Click command `sync` with `--teams` (comma-separated) and `--repo-dir` option
- `--repo-dir` defaults to cwd, points to a local clone of the target repo (e.g., `gigaverse-app/linear-git`)
- This repo (issueclaw) contains NO Linear data — only the tool code
- Fetches teams, filters by specified keys
- For each team: fetches issues with comments
- Fetches projects, initiatives, documents
- Renders each to .md using render.py
- Writes files to correct paths under `{repo-dir}/linear/`
- Builds id-map at `{repo-dir}/.sync/id-map.json`
- Saves state at `{repo-dir}/.sync/state.json`

**Step 4:** Run: `uv run pytest tests/test_initial_sync.py -v` — Expected: PASS

**Step 5:** Register command in main.py, commit: `git commit -m "feat: add initial sync command (Phase 1 complete)"`

---

### Task 7.5: Update Documentation and Plan with Phase 1 Learnings

**Goal:** Capture everything learned during Phase 1 so future development and contributors start with accurate knowledge.

**Key learnings to document:**
1. **Linear API complexity limits:** GraphQL queries are limited to 10000 complexity. Rich project queries (with milestones, updates, members, initiatives, documents) need page size of 5 instead of 50. Issue queries with inline comments can handle 50 per page.
2. **Rate limiting quirks:** Linear returns HTTP 400 (not 429) with "RATELIMITED" in the body for rate limits. Must check response body, not just status code.
3. **Inline comments:** Comments can be fetched inline with issues (up to 50 per issue) to avoid N+1 API calls. This reduced 3300+ calls to ~70.
4. **Connection reuse:** Must use a persistent httpx.AsyncClient for connection pooling to avoid 3000+ TCP connections.
5. **Project slugs:** Linear's `slugId` is a hex hash, not readable. We generate slugs from project names using `_slugify()`.
6. **Content vs description:** Projects and initiatives have both `description` (short) and `content` (rich markdown body). Content should be preferred as the body when present.
7. **Data richness:** Projects have status updates, milestones, members, teams, initiatives, documents, health, progress, scope. All should be synced for the files to be useful.
8. **Issue lifecycle dates:** `startedAt`, `completedAt`, `canceledAt` are valuable for tracking issue lifecycle. `projectMilestone` and `parent` provide project hierarchy context.
9. **Field sync strategy decision needed:** See Task 7.6.

**Files to update:**
- `docs/plans/2026-03-09-issueclaw-implementation.md` — Update API response shapes, model definitions, and query examples
- `README.md` — Update with current feature set and data model
- `.claude/MEMORY.md` or project memory — Record patterns and pitfalls

---

### Task 7.6: Field Sync Strategy — Decision: Explicit Whitelist with Rich Defaults

**Decision: Keep explicit whitelist approach, but ensure it's comprehensive.**

**Rationale:**
- GraphQL requires explicit field selection — there's no "fetch all fields" option
- The complexity limit (10000) means we can't blindly add every field anyway
- The real problem wasn't the whitelist approach — it was that we didn't include enough fields initially
- A blacklist approach would require schema introspection and dynamic query building, adding significant complexity for marginal benefit

**Implementation:**
1. GraphQL queries explicitly list all useful fields (already done)
2. Models have typed fields for everything we fetch (already done)
3. Renderers output all model fields to markdown (already done)
4. When Linear adds new fields, we add them to queries/models/renderers as needed
5. The API shapes section above serves as the reference for what we fetch

**Fields intentionally excluded:**
- `archivedAt` — archived entities are excluded from queries
- `trashed` — trashed entities are excluded
- `sortOrder`, `prioritySortOrder` — UI ordering, not meaningful in git
- `reactionData` — emoji reactions not represented in markdown
- `facets` — internal UI metadata
- `contentState`, `descriptionState` — internal editor state (ProseMirror JSON)
- `updateReminderFrequency*` — notification settings
- `snoozedUntilAt`, `snoozedBy` — temporary UI state
- `branchName` — derived from identifier, not useful to duplicate
- `infoSnapshot`, `diff`, `diffMarkdown` — internal project update metadata
- `scopeHistory`, `completedScopeHistory`, `progressHistory` — time series data (too large)
- `labelIds`, `previousIdentifiers` — redundant with resolved names/identifiers

**Status: DECIDED. No further action needed.**

---

## Phase 2: Webhook-Driven Pull (Real-Time)

### Task 8: Apply Webhook Script

**Files:**
- Create: `src/issueclaw/commands/apply_webhook.py`
- Test: `tests/test_apply_webhook.py`

Receives webhook payload from env var `WEBHOOK_PAYLOAD`, determines entity type and file path, renders .md, writes file. For comments: reads parent issue file, updates comments section, writes back.

Key: No API calls needed - webhook payload has full entity data.

Tests should cover: issue create, issue update, issue remove, comment create, comment update, comment remove (embedded in parent issue file).

**Step 1-5:** Follow TDD cycle as above.

Commit: `git commit -m "feat: add webhook application script (Phase 2)"`

---

### Task 9: Cloudflare Worker and GitHub Actions Workflows

**Files:**
- Create: `workers/issueclaw-webhook-proxy/worker.js`
- Create: `workers/issueclaw-webhook-proxy/wrangler.toml`
- Create: `.github/workflows/issueclaw-webhook.yaml`

The CF Worker validates Linear webhook signature and forwards to GitHub repository_dispatch. The workflow triggers on repository_dispatch, runs apply_webhook.py, commits as issueclaw-bot.

No Python tests needed for JS/YAML files. Manual verification.

Commit: `git commit -m "feat: add CF worker and webhook workflow (Phase 2 complete)"`

---

## Phase 3: Push Sync (Git to Linear)

### Task 10: Diff Parser

**Files:**
- Create: `src/issueclaw/diff.py`
- Test: `tests/test_diff.py`

Parses old and new versions of .md file into field-level diff. Strategy: parse both files, diff frontmatter dicts field-by-field, diff body, diff comments by comment-id.

Tests should cover: field changes, body changes, comment add/remove/edit, no changes.

**Step 1-5:** Follow TDD cycle.

Commit: `git commit -m "feat: add diff parser for markdown files"`

---

### Task 11: Push Sync Command

**Files:**
- Create: `src/issueclaw/commands/push.py`
- Test: `tests/test_push.py`

Orchestrates push sync: runs git diff, iterates changed files, calls diff parser, maps to Linear API calls, executes API calls, updates id-map.

Handles: Added files (create in Linear, writeback ID), Modified files (minimal API update), Deleted files (archive in Linear).

**Step 1-5:** Follow TDD cycle.

Commit: `git commit -m "feat: add push sync command"`

---

### Task 12: Push Workflow and Loop Prevention

**Files:**
- Create: `.github/workflows/issueclaw-push.yaml`

Push workflow triggers on push to main modifying `linear/**`. Skips if commit author is issueclaw-bot. Runs push.py, commits updated IDs as issueclaw-bot.

Commit: `git commit -m "feat: add push workflow with loop prevention (Phase 3 complete)"`

---

## Phase 4: Polish

### Task 13: CLI Enhancements

- Add `issueclaw status` command (show sync state)
- Add `issueclaw diff` command (preview what would be pushed)
- Error handling and retry logic in API client
- Rich output formatting

### Task 14: Recovery and Health

- Periodic consistency check (compare git state vs Linear)
- Webhook delivery failure detection
- Metrics logging
