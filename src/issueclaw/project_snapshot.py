"""One writer for project reference pages and their independently owned updates."""

from issueclaw.models import LinearProject, project_update_author
from issueclaw.paths import entity_path, update_file_slug
from issueclaw.render import render_project, render_project_update
from issueclaw.sync_state import SyncState


def write_project(state: SyncState, project: LinearProject) -> None:
    # Stable source identity disambiguates same-author/same-day updates. Existing
    # ownership checks apply to each child; a project is not its update's UUID.
    for update in project.project_updates:
        if not isinstance(update.get("id"), str) or not update["id"]:
            raise ValueError("Project update identity is required")
    state.write_entity(
        entity_path("project", slug=project.slug), project.id, render_project(project)
    )
    for update in project.project_updates:
        author = project_update_author(update)
        slug = update_file_slug(update.get("createdAt", ""), author, update["id"])
        state.write_entity(
            entity_path("update", project_slug=project.slug, slug=slug),
            update["id"],
            render_project_update(update),
        )
