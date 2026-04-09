import click

from issueclaw.commands.apply_webhook import apply_webhook_command
from issueclaw.commands.create import create_group
from issueclaw.commands.diff_cmd import diff_command
from issueclaw.commands.init import init_command
from issueclaw.commands.pull import pull_command
from issueclaw.commands.push import push_command
from issueclaw.commands.self_cmd import self_group
from issueclaw.commands.status import status_command
from issueclaw.commands.workflows_cmd import workflows_group


@click.group()
@click.version_option(package_name="issueclaw")
@click.option(
    "--json", "json_mode", is_flag=True, help="Output strict JSON for agents."
)
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
cli.add_command(push_command)
cli.add_command(create_group)
cli.add_command(status_command)
cli.add_command(diff_command)
cli.add_command(init_command)
cli.add_command(self_group)
cli.add_command(workflows_group)


if __name__ == "__main__":
    cli()
