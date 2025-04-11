"""Secrets commands for the Reflex Cloud CLI."""

from typing import List, Optional

import typer
from tabulate import tabulate
from typing_extensions import Annotated

from reflex_cli import constants
from reflex_cli.utils import console
from reflex_cli.utils.exceptions import NotAuthenticatedError

secrets_cli = typer.Typer()


@secrets_cli.command(name="list")
def get_secrets(
    app_id: str = typer.Argument(..., help="The ID of the application."),
    token: Optional[str] = typer.Option(None, help="The authentication token."),
    loglevel: Annotated[
        constants.LogLevel, typer.Option(help="The log level to use.")
    ] = constants.LogLevel.INFO,
    as_json: bool = typer.Option(
        False, "-j", "--json", help="Whether to output the result in JSON format."
    ),
    interactive: bool = typer.Option(
        True, "-i", "--interactive", help="Whether to use interactive mode."
    ),
):
    """Retrieve secrets for a given application."""
    from reflex_cli.utils import hosting

    console.set_log_level(loglevel)

    try:
        authenticated_client = hosting.get_authenticated_client(
            token=token, interactive=interactive
        )
        secrets = hosting.get_secrets(app_id=app_id, client=authenticated_client)
        if "failed" in secrets:
            console.error(secrets)
            raise typer.Exit(1)
        if as_json:
            console.print(secrets)
            return
        if secrets:
            headers = ["Keys"]
            table = [[key] for key in secrets]
            console.print(tabulate(table, headers=headers))
        else:
            console.print(str(secrets))
    except NotAuthenticatedError as err:
        console.error("You are not authenticated. Run `reflex login` to authenticate.")
        raise typer.Exit(1) from err


@secrets_cli.command(name="update")
def update_secrets(
    app_id: str = typer.Argument(..., help="The ID of the application."),
    envfile: Optional[str] = typer.Option(
        None,
        "--envfile",
        help="The path to an env file to use. Will override any envs set manually.",
    ),
    envs: List[str] = typer.Option(
        list(),
        "--env",
        help="The environment variables to set: <key>=<value>. Required if envfile is not specified. For multiple envs, repeat this option, e.g. --env k1=v2 --env k2=v2.",
    ),
    reboot: bool = typer.Option(
        False,
        "--reboot",
        help="Automatically reboot your site with the new secrets",
    ),
    token: Optional[str] = typer.Option(None, help="The authentication token."),
    loglevel: Annotated[
        constants.LogLevel, typer.Option(help="The log level to use.")
    ] = constants.LogLevel.INFO,
    interactive: bool = typer.Option(
        True, "-i", "--interactive", help="Whether to use interactive mode."
    ),
):
    """Update secrets for a given application."""
    from reflex_cli.utils import hosting

    console.set_log_level(loglevel)
    authenticated_client = hosting.get_authenticated_client(
        token=token, interactive=interactive
    )

    if envfile is None and not envs:
        console.error("--envfile or --env must be provided")
        raise typer.Exit(1)

    if envfile and envs:
        console.warn("--envfile is set; ignoring --env")

    secrets = {}

    if envfile:
        try:
            from dotenv import dotenv_values  # type: ignore

            secrets = dotenv_values(envfile)
        except ImportError:
            console.error(
                """The `python-dotenv` package is required to load environment variables from a file. Run `pip install "python-dotenv>=1.0.1"`."""
            )

    else:
        secrets = hosting.process_envs(envs)
    hosting.update_secrets(
        app_id=app_id, secrets=secrets, reboot=reboot, client=authenticated_client
    )


@secrets_cli.command(name="delete")
def delete_secret(
    app_id: str = typer.Argument(..., help="The ID of the application."),
    key: str = typer.Argument(..., help="The key of the secret to delete."),
    token: Optional[str] = typer.Option(None, help="The authentication token."),
    reboot: bool = typer.Option(
        False,
        "--reboot",
        help="Automatically reboot your site with the new secrets",
    ),
    loglevel: Annotated[
        constants.LogLevel, typer.Option(help="The log level to use.")
    ] = constants.LogLevel.INFO,
    interactive: bool = typer.Option(
        True, "-i", "--interactive", help="Whether to use interactive mode."
    ),
):
    """Delete a secret for a given application."""
    from reflex_cli.utils import hosting

    console.set_log_level(loglevel)
    try:
        authenticated_client = hosting.get_authenticated_client(
            token=token, interactive=interactive
        )
        result = hosting.delete_secret(
            app_id=app_id, key=key, reboot=reboot, client=authenticated_client
        )
        if "failed" in result:
            console.error(result)
            raise typer.Exit(1)
        console.success("Successfully deleted secret.")
    except NotAuthenticatedError as err:
        console.error("You are not authenticated. Run `reflex login` to authenticate.")
        raise typer.Exit(1) from err
