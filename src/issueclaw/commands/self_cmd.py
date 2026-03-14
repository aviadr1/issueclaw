"""Self-management commands: update, detect, skill."""

from __future__ import annotations

import importlib.resources
import subprocess
import sys

import click


GITHUB_REPO = "https://github.com/aviadr1/issueclaw.git"


@click.group("self")
def self_group() -> None:
    """Self-management commands (update, detect, skill)."""


@self_group.command("update")
def self_update() -> None:
    """Upgrade issueclaw to the latest version from GitHub."""
    click.echo(f"Upgrading issueclaw from {GITHUB_REPO} ...")
    result = subprocess.run(
        [
            "uv",
            "tool",
            "install",
            "--reinstall",
            f"git+{GITHUB_REPO}",
        ],
        check=False,
    )
    if result.returncode == 0:
        click.echo("issueclaw upgraded successfully.")
    else:
        click.echo("Upgrade failed. Is 'uv' installed?", err=True)
        sys.exit(result.returncode)


@self_group.command("detect")
def self_detect() -> None:
    """Show installation info (version, executable path, Python)."""
    import issueclaw

    version = getattr(issueclaw, "__version__", "unknown")
    click.echo(f"issueclaw version : {version}")
    click.echo(f"executable        : {sys.executable}")
    click.echo(f"Python            : {sys.version.split()[0]}")
    click.echo(f"source repo       : {GITHUB_REPO}")


@self_group.command("skill")
def self_skill() -> None:
    """Print the bundled SKILL.md agent usage guide."""
    skill_text = importlib.resources.files("issueclaw").joinpath("SKILL.md").read_text()
    click.echo(skill_text)
