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
    assert issue.assignee == "Marek Chabiera"
    assert issue.team == "Engineering"
    assert issue.due_date is None
    assert issue.url == "https://linear.app/gigaverse/issue/ENG-6148"


def test_issue_from_api_minimal():
    """INVARIANT: Issue model handles minimal API response with defaults."""
    data = {
        "id": "uuid-min",
        "identifier": "AI-1",
        "title": "Minimal issue",
        "status": "Backlog",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    issue = LinearIssue.from_api(data)
    assert issue.id == "uuid-min"
    assert issue.identifier == "AI-1"
    assert issue.description is None
    assert issue.priority is None
    assert issue.priority_name is None
    assert issue.labels == []
    assert issue.assignee is None
    assert issue.comments == []


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
    assert comment.author_id == "17c35488-uuid"
    assert comment.created == "2025-12-09T15:13:34.879Z"


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
    assert project.teams == [{"id": "84b57c2b-uuid", "name": "Backend", "key": "BE"}]


def test_project_slug_generation():
    """INVARIANT: Project generates slug from name when not provided by API."""
    data = {
        "id": "uuid",
        "name": "Chapter Detection Feature",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "status": {"name": "Started"},
        "teams": [],
    }
    project = LinearProject.from_api(data)
    assert project.slug == "chapter-detection-feature"


def test_document_from_api_response():
    """INVARIANT: Document model correctly parses Linear API response."""
    data = {
        "id": "68120669-uuid",
        "title": "Pre-Live Deep Dive",
        "content": "# Meeting Notes\nDetails here.",
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
    assert doc.content == "# Meeting Notes\nDetails here."
    assert doc.project_name == "Improve Pre Live"
