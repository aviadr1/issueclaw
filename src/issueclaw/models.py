"""Pydantic models for Linear entities."""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, Field


class LinearComment(BaseModel):
    """A Linear issue comment."""

    id: str
    body: str
    author_name: str = ""
    author_id: str | None = None
    created: str = ""
    updated: str = ""

    @classmethod
    def from_api(cls, data: dict) -> Self:
        author = data.get("user") or data.get("author") or {}
        return cls(
            id=data["id"],
            body=data.get("body", ""),
            author_name=author.get("name", ""),
            author_id=author.get("id"),
            created=data.get("createdAt", ""),
            updated=data.get("updatedAt", ""),
        )


class LinearIssue(BaseModel):
    """A Linear issue."""

    id: str
    identifier: str
    title: str
    description: str | None = None
    status: str = ""
    priority: int | None = None
    priority_name: str | None = None
    assignee: str | None = None
    assignee_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    team: str | None = None
    team_id: str | None = None
    team_key: str | None = None
    project: str | None = None
    milestone: str | None = None
    estimate: int | None = None
    due_date: str | None = None
    created: str = ""
    updated: str = ""
    url: str = ""
    comments: list[LinearComment] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> Self:
        priority_obj = data.get("priority")
        priority_val = None
        priority_name = None
        if isinstance(priority_obj, dict):
            priority_val = priority_obj.get("value")
            priority_name = priority_obj.get("name")
        elif isinstance(priority_obj, int):
            priority_val = priority_obj

        return cls(
            id=data["id"],
            identifier=data.get("identifier", ""),
            title=data.get("title", ""),
            description=data.get("description"),
            status=data.get("status", ""),
            priority=priority_val,
            priority_name=priority_name,
            assignee=data.get("assignee"),
            assignee_id=data.get("assigneeId"),
            labels=data.get("labels", []),
            team=data.get("team"),
            team_id=data.get("teamId"),
            team_key=data.get("teamKey"),
            project=data.get("project"),
            milestone=data.get("milestone"),
            estimate=data.get("estimate"),
            due_date=data.get("dueDate"),
            created=data.get("createdAt", ""),
            updated=data.get("updatedAt", ""),
            url=data.get("url", ""),
        )


def _extract_nodes(data: list | dict) -> list:
    """Extract nodes from a GraphQL connection object or pass through a list."""
    if isinstance(data, dict):
        return data.get("nodes", [])
    return data


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


class LinearProject(BaseModel):
    """A Linear project."""

    id: str
    name: str
    slug: str = ""
    description: str | None = None
    status: str = ""
    lead_name: str | None = None
    lead_id: str | None = None
    priority: int | None = None
    start_date: str | None = None
    target_date: str | None = None
    labels: list[str] = Field(default_factory=list)
    url: str = ""
    created: str = ""
    updated: str = ""
    teams: list[dict] = Field(default_factory=list)
    milestones: list[dict] = Field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> Self:
        lead = data.get("lead") or {}
        status_obj = data.get("status") or {}
        status_name = status_obj.get("name", "") if isinstance(status_obj, dict) else str(status_obj)

        # Extract label names
        labels_raw = data.get("labels", [])
        if labels_raw and isinstance(labels_raw[0], dict):
            labels = [lb.get("name", "") for lb in labels_raw]
        else:
            labels = labels_raw

        return cls(
            id=data["id"],
            name=data.get("name", ""),
            slug=_slugify(data.get("name", "")),
            description=data.get("description"),
            status=status_name,
            lead_name=lead.get("name"),
            lead_id=lead.get("id"),
            priority=data.get("priority"),
            start_date=data.get("startDate"),
            target_date=data.get("targetDate"),
            labels=labels,
            url=data.get("url", ""),
            created=data.get("createdAt", ""),
            updated=data.get("updatedAt", ""),
            teams=_extract_nodes(data.get("teams", [])),
            milestones=_extract_nodes(data.get("projectMilestones") or data.get("milestones", [])),
        )


class LinearDocument(BaseModel):
    """A Linear document."""

    id: str
    title: str
    content: str | None = ""
    slug_id: str = ""
    url: str = ""
    creator_name: str | None = None
    creator_id: str | None = None
    created: str = ""
    updated: str = ""
    project_name: str | None = None
    project_id: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> Self:
        creator = data.get("creator") or {}
        project = data.get("project") or {}

        return cls(
            id=data["id"],
            title=data.get("title", ""),
            content=data.get("content", ""),
            slug_id=data.get("slugId", ""),
            url=data.get("url", ""),
            creator_name=creator.get("name"),
            creator_id=creator.get("id"),
            created=data.get("createdAt", ""),
            updated=data.get("updatedAt", ""),
            project_name=project.get("name"),
            project_id=project.get("id"),
        )


class LinearInitiative(BaseModel):
    """A Linear initiative."""

    id: str
    name: str
    description: str | None = None
    status: str = ""
    owner_name: str | None = None
    owner_id: str | None = None
    target_date: str | None = None
    created: str = ""
    updated: str = ""

    @classmethod
    def from_api(cls, data: dict) -> Self:
        owner = data.get("owner") or {}

        return cls(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            status=data.get("status", ""),
            owner_name=owner.get("name"),
            owner_id=owner.get("id"),
            target_date=data.get("targetDate"),
            created=data.get("createdAt", ""),
            updated=data.get("updatedAt", ""),
        )
