"""Init command: set up issueclaw in a repository."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import click
from issueclaw.workflow_templates import copy_workflow_templates


_WEBHOOK_RESOURCE_TYPES = ["Issue", "Comment", "Project", "Document"]


def _find_api_key(repo_dir: Path) -> str | None:
    """Find LINEAR_API_KEY from environment or .env file."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key.strip()
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
    import subprocess

    env = {**os.environ, "LINEAR_API_KEY": api_key}
    subprocess.run(
        ["issueclaw", "pull", "--repo-dir", str(repo_dir)],
        env=env,
        check=True,
    )


def _create_linear_webhook(
    api_key: str, webhook_url: str
) -> tuple[str | None, str | None]:
    """Create a webhook in Linear. Returns (webhook_id, signing_secret)."""
    import httpx

    signing_secret = secrets.token_hex(32)

    query = """
    mutation WebhookCreate($input: WebhookCreateInput!) {
        webhookCreate(input: $input) {
            success
            webhook {
                id
                enabled
            }
        }
    }
    """
    variables = {
        "input": {
            "url": webhook_url,
            "resourceTypes": _WEBHOOK_RESOURCE_TYPES,
            "allPublicTeams": True,
            "secret": signing_secret,
            "label": "issueclaw",
        }
    }

    response = httpx.post(
        "https://api.linear.app/graphql",
        json={"query": query, "variables": variables},
        headers={"Authorization": api_key},
    )
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        errors = data["errors"]
        if any("url not unique" in str(e.get("message", "")) for e in errors):
            return None, None
        raise click.ClickException(f"Linear API error: {errors}")

    result = data["data"]["webhookCreate"]
    if not result["success"]:
        raise click.ClickException("Failed to create Linear webhook")

    return result["webhook"]["id"], signing_secret


def _copy_workflow_files(repo_dir: Path) -> None:
    """Copy workflow templates to .github/workflows/."""
    copy_workflow_templates(repo_dir)


@click.command("init")
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.option(
    "--webhook-url",
    default=None,
    help="URL of the webhook proxy (CF Worker). Creates a Linear webhook if provided.",
)
@click.pass_context
def init_command(ctx: click.Context, repo_dir: Path, webhook_url: str | None) -> None:
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

    # Create Linear webhook
    if webhook_url:
        webhook_id, signing_secret = _create_linear_webhook(api_key, webhook_url)
        if webhook_id:
            click.echo(f"Created Linear webhook: {webhook_id}")
            click.echo(f"Webhook signing secret: {signing_secret}")
            click.echo("Set this as LINEAR_WEBHOOK_SECRET in your CF Worker.")
        else:
            click.echo("Linear webhook already exists for this URL.")
    else:
        click.echo("Skipped webhook creation (use --webhook-url to create one).")

    # Set GitHub secret
    if _run_gh_secret_set(api_key):
        click.echo("Set LINEAR_API_KEY as GitHub repo secret")
    else:
        click.echo(
            "Could not set GitHub secret (gh CLI not available). Set it manually."
        )

    # Run initial pull
    click.echo("Running initial pull...")
    _run_initial_pull(repo_dir, api_key)
    click.echo("Done! issueclaw is set up.")
