"""Guard command: fail fast on misplaced new files under linear/."""

from __future__ import annotations

import json
from pathlib import Path

import click

from issueclaw.commands.push import (
    detect_git_changes,
    find_misplaced_added_files,
    format_misplaced_added_files_error,
)


@click.command("guard")
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.option(
    "--strict/--no-strict",
    default=True,
    help="Fail with non-zero exit when misplaced additions are found.",
)
@click.pass_context
def guard_command(ctx: click.Context, repo_dir: Path, strict: bool) -> None:
    """Validate that newly added linear/ files use supported creation paths."""
    changes = detect_git_changes(repo_dir)
    misplaced = find_misplaced_added_files(changes, repo_dir)

    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    if json_mode:
        click.echo(
            json.dumps(
                {
                    "repo_dir": str(repo_dir),
                    "misplaced_added_files": misplaced,
                    "valid": not misplaced,
                }
            )
        )
    elif misplaced:
        click.echo(format_misplaced_added_files_error(misplaced))
    else:
        click.echo("Guard check passed: no misplaced new linear files.")

    if strict and misplaced:
        raise click.ClickException(
            f"Guard failed: {len(misplaced)} misplaced new linear file(s)."
        )

