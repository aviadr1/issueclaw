import click

from issueclaw.commands.apply_webhook import apply_webhook_command
from issueclaw.commands.pull import pull_command


@click.group()
@click.version_option(package_name="issueclaw")
@click.option("--json", "json_mode", is_flag=True, help="Output strict JSON for agents.")
@click.option("--verbose", "-v", count=True)
@click.option("--quiet", "-q", count=True)
@click.pass_context
def cli(ctx, json_mode, verbose, quiet):
    """issueclaw - Issues as Code. Bidirectional sync between Linear and Git."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


cli.add_command(pull_command)
cli.add_command(apply_webhook_command)


if __name__ == "__main__":
    cli()
