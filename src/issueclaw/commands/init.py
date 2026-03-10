"""Init command: set up issueclaw in a repository."""

from __future__ import annotations

import importlib.resources
import os
import shutil
from pathlib import Path

import click


def _find_api_key(repo_dir: Path) -> str | None:
    """Find LINEAR_API_KEY from environment or .env file."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key
    env_file = repo_dir / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("LINEAR_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def _run_gh_secret_set(api_key: str) -> bool:
    """Set LINEAR_API_KEY as a GitHub repo secret via gh CLI."""
    import subprocess

    try:
        result = subprocess.run(
            ["gh", "secret", "set", "LINEAR_API_KEY"],
            input=api_key,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _run_initial_pull(repo_dir: Path, api_key: str) -> None:
    """Run issueclaw pull to populate linear/ directory."""
    from issueclaw.commands.pull import pull_command

    ctx = click.Context(pull_command, obj={"json": False, "verbose": 0, "quiet": 0})
    with ctx:
        pull_command.invoke(ctx)


def _copy_workflow_files(repo_dir: Path) -> None:
    """Copy workflow templates to .github/workflows/."""
    wf_dir = repo_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)

    workflows_pkg = importlib.resources.files("issueclaw") / "workflows"
    for name in ("issueclaw-webhook.yaml", "issueclaw-push.yaml"):
        src = workflows_pkg / name
        dst = wf_dir / name
        dst.write_text(src.read_text())


@click.command("init")
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.pass_context
def init_command(ctx: click.Context, repo_dir: Path) -> None:
    """Set up issueclaw in a repository."""
    api_key = _find_api_key(repo_dir)
    if not api_key:
        api_key = click.prompt("Enter your LINEAR_API_KEY")

    # Save to .env
    env_file = repo_dir / ".env"
    if not env_file.exists() or "LINEAR_API_KEY" not in env_file.read_text():
        with open(env_file, "a") as f:
            f.write(f"\nLINEAR_API_KEY={api_key}\n")
        click.echo("Saved LINEAR_API_KEY to .env")

    # Ensure .env is in .gitignore
    gitignore = repo_dir / ".gitignore"
    if not gitignore.exists() or ".env" not in gitignore.read_text():
        with open(gitignore, "a") as f:
            f.write("\n.env\n")
        click.echo("Added .env to .gitignore")

    # Copy workflow files
    _copy_workflow_files(repo_dir)
    click.echo("Copied workflow files to .github/workflows/")

    # Set GitHub secret
    if _run_gh_secret_set(api_key):
        click.echo("Set LINEAR_API_KEY as GitHub repo secret")
    else:
        click.echo("Could not set GitHub secret (gh CLI not available). Set it manually.")

    # Run initial pull
    click.echo("Running initial pull...")
    _run_initial_pull(repo_dir, api_key)
    click.echo("Done! issueclaw is set up.")
