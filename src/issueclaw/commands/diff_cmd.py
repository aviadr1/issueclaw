"""Diff command: preview what would be pushed to Linear."""

from __future__ import annotations

import json
from pathlib import Path

import click

from issueclaw.commands.push import detect_git_changes
from issueclaw.diff import diff_markdown


@click.command("diff")
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.pass_context
def diff_command(ctx: click.Context, repo_dir: Path) -> None:
    """Preview changes that would be pushed to Linear."""
    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    changes = detect_git_changes(repo_dir)

    if not changes:
        if json_mode:
            click.echo("[]")
        else:
            click.echo("No changes detected in linear/ files.")
        return

    if json_mode:
        result = []
        for change in changes:
            entry: dict = {
                "path": change.path,
                "change_type": change.change_type,
            }
            if (
                change.change_type == "modified"
                and change.old_content
                and change.new_content
            ):
                md_diff = diff_markdown(change.old_content, change.new_content)
                entry["frontmatter_changes"] = {
                    k: {"old": v.old, "new": v.new}
                    for k, v in md_diff.frontmatter_changes.items()
                }
                entry["body_changed"] = md_diff.body_changed
                entry["comments_added"] = len(md_diff.comments_added)
                entry["comments_removed"] = len(md_diff.comments_removed)
                entry["comments_edited"] = len(md_diff.comments_edited)
                entry["comments_pending"] = len(md_diff.comments_pending)
                entry["updates_pending"] = len(md_diff.updates_pending)
            result.append(entry)
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        click.echo(f"{len(changes)} file(s) changed:\n")
        for change in changes:
            click.echo(f"  {change.change_type.upper():10s} {change.path}")

            if (
                change.change_type == "modified"
                and change.old_content
                and change.new_content
            ):
                md_diff = diff_markdown(change.old_content, change.new_content)
                for field_name, field_diff in md_diff.frontmatter_changes.items():
                    click.echo(
                        f"             {field_name}: {field_diff.old} → {field_diff.new}"
                    )
                if md_diff.body_changed:
                    click.echo("             body: changed")
                if md_diff.comments_pending:
                    click.echo(
                        f"             comments: +{len(md_diff.comments_pending)} pending (will push)"
                    )
                if md_diff.comments_added:
                    click.echo(
                        f"             comments: {len(md_diff.comments_added)} synced (already in Linear)"
                    )
                if md_diff.comments_removed:
                    click.echo(
                        f"             comments: -{len(md_diff.comments_removed)} removed"
                    )
                if md_diff.comments_edited:
                    click.echo(
                        f"             comments: ~{len(md_diff.comments_edited)} edited"
                    )
                if md_diff.updates_pending:
                    click.echo(
                        f"             updates: +{len(md_diff.updates_pending)} pending (will push)"
                    )
