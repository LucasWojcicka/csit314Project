"""Hosting service related utilities."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
import webbrowser
from enum import Enum
from http import HTTPStatus
from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import urljoin

import httpx
import typer
import yaml
from tabulate import tabulate

import reflex_cli.constants as constants
from reflex_cli.core.config import Config
from reflex_cli.utils import console, dependency
from reflex_cli.utils.dependency import is_valid_url
from reflex_cli.utils.exceptions import (
    GetAppError,
    NotAuthenticatedError,
    ResponseError,
    ScaleAppError,
    ScaleParamError,
)


class ScaleType(str, Enum):
    """The scale type for an application."""

    SIZE = "size"
    REGION = "region"


@dataclasses.dataclass
class ScaleAppCliArgs:
    """CLI arguments for scaling an application."""

    type: Optional[ScaleType] = None
    regions: Optional[dict[str, int]] = None
    vm_type: Optional[str] = None

    @classmethod
    def create(
        cls,
        regions: Optional[List[str] | dict[str, int]] = None,
        vm_type: Optional[str] = None,
        scale_type: Optional[ScaleType | str] = None,
    ) -> ScaleAppCliArgs:
        """Create a ScaleAppCliArgs object.

        Args:
            regions: The regions to scale to.
            vm_type: The VM size to scale to.
            scale_type: The scale type.

        Returns:
            An instance of ScaleAppCliArgs.

        Raises:
            ScaleAppError: If both regions and vm_type are provided.

        """
        if isinstance(regions, list):
            regions = {region: 1 for region in regions}

        if vm_type is not None and regions:
            raise ScaleAppError(
                "Only one of --vm-type or --regions should be provided."
            )
        return cls(ScaleType(scale_type) if scale_type else None, regions, vm_type)

    @property
    def is_valid(self) -> bool:
        """Check if the CLI arguments are valid.

        Returns:
            bool: True if either vmtype or regions is set.

        """
        return bool(self.regions or self.vm_type)


class Regions(TypedDict):
    """Regions for scaling an application."""

    name: str
    number_of_machines: int


@dataclasses.dataclass
class ScaleParams:
    """Parameters for scaling an application."""

    type: ScaleType | None = None
    vm_type: str | None = None
    regions: Regions | None = None

    @classmethod
    def create(
        cls,
        scale_type: ScaleType | None = None,
        vm_type: str | None = None,
        regions: list[str] | dict[str, int] | None = None,
    ) -> ScaleParams:
        """Create a ScaleParams object.

        Args:
            scale_type: The scale type.
            vm_type: The VM type to scale to.
            regions: The regions to scale to.

        Returns:
            ScaleParams: The created ScaleParams object.

        """
        if isinstance(regions, list):
            regions = {region: 1 for region in regions}
        return cls(scale_type, vm_type, Regions(**regions) if regions else None)  # type: ignore

    @classmethod
    def from_config(cls, config: Config) -> ScaleParams:
        """Create a ScaleParams object from a Config object.

        Args:
            config: The Config object.

        Returns:
            The created ScaleParams object.

        """
        return cls.create(vm_type=config.vmtype, regions=config.regions)  # type: ignore

    def set_type(self, scale_type: ScaleType | str | None) -> ScaleParams:
        """Set the scale type.

        Args:
            scale_type: The scale type.

        Returns:
            The ScaleParams object with the scale type set.

        """
        return ScaleParams(
            ScaleType(scale_type) if scale_type else None, self.vm_type, self.regions
        )

    def set_type_from_cli_args(self, cli_args: ScaleAppCliArgs) -> ScaleParams:
        """Set the scale type from CLI arguments.

        Args:
            cli_args: The CLI arguments.

        Returns:
            The ScaleParams object with the scale type set.

        Raises:
            ScaleParamError: If the scale type is not provided when using cloud.yml.

        """
        scale_type = cli_args.type

        if scale_type is None and not cli_args.is_valid:
            raise ScaleParamError(
                "specify the type of scaling using --scale-type when using cloud.yml"
            )

        if scale_type is not None and cli_args.is_valid:
            console.warn(
                "using --scale-type with --regions or --vm-type will have no effect"
            )

        if not cli_args.is_valid:
            if scale_type == ScaleType.SIZE and not cli_args.vm_type:
                raise ScaleParamError(
                    f"'vmtype' should be provided in the {constants.Dirs.CLOUD} for size scaling"
                )

            if scale_type == ScaleType.REGION and not cli_args.regions:
                raise ScaleParamError(
                    f"'regions' should be provided in the {constants.Dirs.CLOUD} for region scaling"
                )

        if cli_args.is_valid:
            return self.set_type(
                ScaleType(ScaleType.REGION)
                if cli_args.regions
                else ScaleType(ScaleType.SIZE)
            )
        return self.set_type(ScaleType(scale_type) if scale_type else None)

    def as_json(self) -> dict[str, Any]:
        """Convert the object to a dictionary.

        Returns:
            dict: The object as a dictionary.

        """
        return (
            {
                "type": str(self.type),
                "size": self.vm_type,
            }
            if self.type == ScaleType.SIZE
            else {
                "type": str(self.type),
                "regions": self.regions,
            }
        )


@dataclasses.dataclass
class UnAuthenticatedClient:
    """A client that is not authenticated."""

    @staticmethod
    def authenticate() -> AuthenticatedClient:
        """Authenticate the client.

        Returns:
            An authenticated client.

        """
        access_token, validated_info = authenticate_on_browser()
        return AuthenticatedClient(access_token, validated_info)


@dataclasses.dataclass
class AuthenticatedClient:
    """A client that is authenticated."""

    token: str
    validated_data: dict[str, Any]


def get_authentication_client(
    token: str | None = None,
) -> AuthenticatedClient | UnAuthenticatedClient:
    """Get an authentication client.

    Args:
        token: The authentication token.

    Returns:
        An authenticated client if the token is valid, otherwise an unauthenticated client.

    """
    access_token = token if token else get_existing_access_token()
    if access_token:
        validated_info = validate_token_with_retries(access_token)
        if validated_info:
            return AuthenticatedClient(access_token, validated_info)
    return UnAuthenticatedClient()


def get_authenticated_client(
    token: str | None = None, interactive: bool = True
) -> AuthenticatedClient:
    """Get an authenticated client.

    Args:
        token: The authentication token.
        interactive: If running in interactive mode.

    Returns:
        An authenticated client.

    Raises:
        Exit: If no token is provided in non-interactive mode.

    """
    if not token and not interactive:
        console.error("Token is required for non-interactive mode.")
        raise typer.Exit(1)

    client = get_authentication_client(token)
    if isinstance(client, UnAuthenticatedClient):
        return client.authenticate()
    return client


class SilentBackgroundBrowser(webbrowser.BackgroundBrowser):
    """A webbrowser.BackgroundBrowser that does not raise exceptions when it fails to open a browser."""

    def open(self, url, new=0, autoraise=True):
        """Open url in a new browser window.

        Args:
            url: The URL to open.
            new: Whether to open in a new window (2), tab (1), or the same tab (0).
            autoraise: Whether to raise the window.

        Returns:
            bool: True if the URL was opened successfully, False otherwise.

        """
        cmdline = [self.name] + [arg.replace("%s", url) for arg in self.args]
        sys.audit("webbrowser.open", url)
        try:
            if sys.platform[:3] == "win":
                p = subprocess.Popen(
                    cmdline, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                p = subprocess.Popen(
                    cmdline,
                    close_fds=True,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return p.poll() is None
        except OSError:
            return False


webbrowser.BackgroundBrowser = SilentBackgroundBrowser


def get_existing_access_token() -> str:
    """Fetch the access token from the existing config if applicable.

    Returns:
        The access token.
        If not found, return empty string for it instead.

    """
    console.debug("Fetching token from existing config...")
    access_token = ""
    try:
        with open(constants.Hosting.HOSTING_JSON, "r") as config_file:
            hosting_config = json.load(config_file)
            access_token = hosting_config.get("access_token", "")
    except Exception as ex:
        console.debug(
            f"Unable to fetch token from {constants.Hosting.HOSTING_JSON} due to: {ex}"
        )
    return access_token


def validate_token(token: str) -> dict[str, Any]:
    """Validate the token with the control plane.

    Args:
        token: The access token to validate.

    Returns:
        Information about the user associated with the token.

    Raises:
        ValueError: if access denied.
        Exception: if runs into timeout, failed requests, unexpected errors. These should be tried again.

    """
    try:
        response = httpx.post(
            urljoin(constants.Hosting.HOSTING_SERVICE, "/v1/authenticate/me"),
            headers=authorization_header(token),
            timeout=constants.Hosting.TIMEOUT,
        )
        if response.status_code == HTTPStatus.FORBIDDEN:
            raise ValueError
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as re:
        console.debug(f"Request to auth server failed due to {re}")
        raise Exception(str(re)) from re
    except httpx.HTTPError as ex:
        console.debug(f"Unable to validate the token due to: {ex}")
        raise Exception("server error") from ex
    except ValueError as ve:
        console.debug(f"Access denied for {token}")
        raise ValueError("access denied") from ve
    except Exception as ex:
        console.debug(f"Unexpected error: {ex}")
        raise Exception("internal errors") from ex


def delete_token_from_config():
    """Delete the invalid token from the config file if applicable."""
    if os.path.exists(constants.Hosting.HOSTING_JSON):
        try:
            with open(constants.Hosting.HOSTING_JSON, "w") as config_file:
                hosting_config = json.load(config_file)
                del hosting_config["access_token"]
                json.dump(hosting_config, config_file)
        except Exception as ex:
            # Best efforts removing invalid token is OK
            console.debug(
                f"Unable to delete the invalid token from config file, err: {ex}"
            )
    # Delete the previous hosting service data if present.
    if os.path.exists(constants.Hosting.HOSTING_JSON_V0):
        os.remove(constants.Hosting.HOSTING_JSON_V0)


def save_token_to_config(token: str):
    """Best efforts cache the token to the config file.

    Args:
        token: The access token to save.

    """
    hosting_config: dict[str, str] = {"access_token": token}

    try:
        if not os.path.exists(constants.Reflex.DIR):
            os.makedirs(constants.Reflex.DIR)
        with open(constants.Hosting.HOSTING_JSON, "w") as config_file:
            json.dump(hosting_config, config_file)
    except Exception as ex:
        console.warn(
            f"Unable to save token to {constants.Hosting.HOSTING_JSON} due to: {ex}"
        )


def requires_access_token() -> str:
    """Fetch the access token from the existing config if applicable.

    Returns:
        The access token. If not found, return empty string for it instead.

    """
    # Check if the user is authenticated

    access_token = get_existing_access_token()
    if not access_token:
        console.debug("No access token found from the existing config.")

    return access_token


def authenticated_token() -> tuple[str, dict[str, Any]]:
    """Fetch the access token from the existing config if applicable and validate it.

    Returns:
        The access token and validated user info.
        If not found, return empty string and dict for it instead.

    """
    # Check if the user is authenticated

    validated_info = {}
    access_token = get_existing_access_token()
    if access_token and not (
        validated_info := validate_token_with_retries(access_token)
    ):
        access_token = ""

    return access_token, validated_info


def authorization_header(token: str) -> dict[str, str]:
    """Construct an authorization header with the specified token as bearer token.

    Args:
        token: The access token to use.

    Returns:
        The authorization header in dict format.

    """
    try:
        uuid.UUID(token, version=4)
    except ValueError:
        return {"Authorization": f"Bearer {token}"}
    else:
        return {"X-API-TOKEN": token}


def requires_authenticated() -> str:
    """Check if the user is authenticated.

    Returns:
        The validated access token or empty string if not authenticated.

    """
    access_token, _ = authenticated_token()
    if access_token:
        return access_token
    access_token, _ = authenticate_on_browser()
    return access_token


def interactive_resolve_project_or_app_name_conflicts(
    items: list[dict],
    rows: list[list[str]],
    headers: list[str],
    conflict_warn_msg: str,
    conflict_ask_msg: str,
    **kwargs,
) -> dict:
    """Interactively resolve conflicts when multiple projects or apps are found.

    Args:
        items: The list of items to choose from.
        rows: The rows to display in the table.
        headers: The headers of the table.
        conflict_warn_msg: The warning message to display.
        conflict_ask_msg: The question to ask the user.
        **kwargs: Additional arguments to pass to tabulate.

    Returns:
        The selected item as a dictionary

    """
    console.warn(conflict_warn_msg)
    console.print(tabulate(rows, headers=headers, **kwargs))
    option = console.ask(
        conflict_ask_msg,
        choices=[str(i) for i in range(len(rows))],
    )
    return items[int(option)]


def search_app(
    app_name: str,
    client: AuthenticatedClient,
    project_id: str | None,
    interactive: bool = False,
) -> dict | None:
    """Search for an application by name within a specific project.

    Args:
        app_name: The name of the application to search for.
        project_id: The ID of the project to search within. If None, searches across all projects.
        client: The authenticated client
        interactive: Whether to interactively resolve conflicts.

    Returns:
        list[dict]: The search results as a list of dicts.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        Exception: If the search request fails.
        Exit: If multiple apps are found and interactive is False.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    if project_id is None:
        project_id = ""
    response = httpx.get(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/apps/search?app_name={app_name}&project_id={project_id}",
        ),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        ex_details = ex.response.json().get("detail")
        raise Exception(ex_details) from ex

    apps = response.json()

    if len(apps) > 1 and not interactive:
        console.error(
            f"Multiple apps with the name {app_name!r} found. Please provide a unique name."
        )
        raise typer.Exit(1)

    elif len(apps) > 1 and interactive:
        return interactive_resolve_project_or_app_name_conflicts(
            apps,
            rows=[
                [f"({i})", x["id"], x["name"], x["project"]["name"], x["project_id"]]
                for i, x in enumerate(apps)
            ],
            headers=["", "App ID", "Name", "Project name", "Project ID"],
            conflict_warn_msg="Found multiple apps with the same name. Select one to continue",
            conflict_ask_msg="Which app would you like to use?",
        )
    elif len(apps) == 1:
        return apps[0]
    else:
        return None


def search_project(
    project_name: str, client: AuthenticatedClient, interactive: bool = False
) -> dict | None:
    """Search for a project by name.

    Args:
        project_name: The name of the application to search for.
        client: The authenticated client
        interactive: Whether to interactively resolve conflicts.

    Returns:
        list[dict]: The search results as a list of dict.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        Exception: If the search request fails.
        Exit: If multiple projects are found and interactive is False.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")

    response = httpx.get(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/project/search?project_name={project_name}",
        ),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        ex_details = ex.response.json().get("detail")
        raise Exception(f"project search failed: {ex_details}") from ex

    projects = response.json()

    if len(projects) > 1 and not interactive:
        console.error(
            f"Multiple projects with the name {project_name!r} found. Please provide a unique name."
        )
        raise typer.Exit(1)

    elif len(projects) > 1 and interactive:
        return interactive_resolve_project_or_app_name_conflicts(
            projects,
            rows=[[f"({i})", x["id"], x["name"]] for i, x in enumerate(projects)],
            headers=["", "Project ID", "Project name"],
            conflict_warn_msg="Found multiple projects with the same name. Select one to continue",
            conflict_ask_msg="Which project would you like to use?",
        )
    elif len(projects) == 1:
        return projects[0]
    else:
        return None


def get_app(app_id: str, client: AuthenticatedClient) -> dict:
    """Retrieve details of a specific application by its ID.

    Args:
        app_id: The ID of the application to retrieve.
        client: The authenticated client

    Returns:
        dict: The application details as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        GetAppError: If the request to get the app fails.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            raise GetAppError(ex.response.json().get("detail")) from ex
        except json.JSONDecodeError:
            raise GetAppError(ex.response.text) from ex
    return response.json()


def create_app(
    app_name: str,
    client: AuthenticatedClient,
    description: str,
    project_id: str | None,
):
    """Create a new application.

    Args:
        app_name: The name of the application.
        description: The description of the application.
        project_id: The ID of the project to associate the application with.
        client: The authenticated client

    Returns:
        dict: The created application details as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        ValueError: If forbidden.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/"),
        json={"name": app_name, "description": description, "project": project_id},
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response_json = response.json()
    if response.status_code == HTTPStatus.FORBIDDEN:
        console.debug(f"Server responded with 403: {response_json.get('detail')}")
        raise ValueError(f"{response_json.get('detail', 'forbidden')}")
    response.raise_for_status()
    return response_json


def get_hostname(
    app_id: str, app_name: str, client: AuthenticatedClient, hostname: str | None
) -> dict:
    """Retrieve or reserve a hostname for a specific application.

    Args:
        app_id: The ID of the application.
        app_name: The name of the application.
        hostname: The desired hostname. If None, a hostname will be generated.
        client: The authenticated client

    Returns:
        dict: The hostname details as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        Exception: If deployment fails or the hostname is invalid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")

    data = {"app_id": app_id, "app_name": app_name}
    if hostname:
        clean_hostname = extract_subdomain(hostname)
        if clean_hostname is None:
            raise Exception("bad hostname provided")
        data["hostname"] = clean_hostname
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/reserve"),
        headers=authorization_header(client.token),
        json=data,
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        if ex_details == "hostname taken":
            return {"error": "hostname taken"}
        raise Exception(f"deployment failed: {ex_details}") from ex
    response_json = response.json()
    return response_json


def extract_subdomain(url):
    """Extract the subdomain from a given URL.

    Args:
        url: The URL to extract the subdomain from.

    Returns:
        str | None: The extracted subdomain, or None if extraction fails.

    """
    from urllib.parse import urlparse

    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    parsed_url = urlparse(url)
    netloc = parsed_url.netloc

    if netloc.startswith("www."):
        netloc = netloc[4:]

    parts = netloc.split(".")

    if len(parts) >= 2 or len(parts) == 1:
        return parts[0]

    return None


def get_secrets(app_id: str, client: AuthenticatedClient) -> str:
    """Retrieve secrets for a given application.

    Args:
        app_id: The ID of the application.
        client: The authenticated client

    Returns:
        The secrets as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}/secrets"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            return ex.response.json().get("detail")
        except json.JSONDecodeError:
            return ex.response.text
    return response.json()


def update_secrets(
    app_id: str,
    secrets: dict,
    client: AuthenticatedClient,
    reboot: bool = False,
):
    """Update secrets for a given application.

    Args:
        app_id: The ID of the application.
        secrets: The secrets to update.
        reboot: Whether to reboot the application with the new secrets.
        client: The authenticated client

    Returns:
        The updated secrets as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/apps/{app_id}/secrets?reboot={'true' if reboot else 'false'}",
        ),
        headers=authorization_header(client.token),
        json={"secrets": secrets},
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def delete_secret(
    app_id: str, key: str, client: AuthenticatedClient, reboot: bool = False
) -> str:
    """Delete a secret for a given application.

    Args:
        app_id: The ID of the application.
        key: The key of the secret to delete.
        reboot: Whether to reboot the application with the updated secrets.
        client: The authenticated client

    Returns:
        The response from the delete operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.delete(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/apps/{app_id}/secrets/{key}?reboot={'true' if reboot else 'false'}",
        ),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            return ex.response.json().get("detail")
        except json.JSONDecodeError:
            return ex.response.text
    return response.json()


def create_project(name: str, client: AuthenticatedClient) -> dict:
    """Create a new project.

    Args:
        name: The name of the project.
        client: The authenticated client

    Returns:
        dict: The created project details as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        ValueError: If the request to create the project fails.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/create"),
        json={"name": name},
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response_json = response.json()
    if response.status_code == HTTPStatus.BAD_REQUEST:
        console.debug(f"Server responded with 400: {response_json.get('detail')}")
        raise ValueError(f"{response_json.get('detail', 'bad request')}")
    response.raise_for_status()
    return response_json


def select_project(project: str, token: str | None = None) -> str:
    """Select a project by its ID.

    Args:
        project: The ID of the project to select.
        token: The authentication token. If None, attempts to authenticate.

    Returns:
        None

    """
    try:
        with open(constants.Hosting.HOSTING_JSON, "r") as config_file:
            hosting_config = json.load(config_file)
        with open(constants.Hosting.HOSTING_JSON, "w") as config_file:
            hosting_config["project"] = project
            json.dump(hosting_config, config_file)
    except Exception as ex:
        return (
            f"failed to fetch token from {constants.Hosting.HOSTING_JSON} due to: {ex}"
        )
    return f"{project} is now selected."


def get_selected_project() -> str | None:
    """Retrieve the currently selected project ID.

    Returns:
        str | None: The ID of the selected project, or None if no project is selected.

    """
    try:
        with open(constants.Hosting.HOSTING_JSON, "r") as config_file:
            hosting_config = json.load(config_file)
            return hosting_config.get("project")
    except Exception as ex:
        console.debug(
            f"Unable to fetch token from {constants.Hosting.HOSTING_JSON} due to: {ex}"
        )
    return None


def get_projects(client: AuthenticatedClient) -> list[dict]:
    """Retrieve a list of projects.

    Args:
        client: The authenticated client.

    Returns:
        The list of projects as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def get_project(project_id: str, client: AuthenticatedClient):
    """Retrieve a single project given the project ID.

    Args:
        project_id: The ID of the project.
        client: The authenticated client

    Returns:
        The project details as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/{project_id}"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def get_project_roles(project_id: str, client: AuthenticatedClient):
    """Retrieve the roles for a project.

    Args:
        project_id: The ID of the project.
        client: The authenticated client

    Returns:
        The roles as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/{project_id}/roles"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def get_project_role_permissions(
    project_id: str, role_id: str, client: AuthenticatedClient
):
    """Retrieve the permissions for a specific role in a project.

    Args:
        project_id: The ID of the project.
        role_id: The ID of the role.
        client: The authenticated client

    Returns:
        The role permissions as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/project/{project_id}/role/{role_id}",
        ),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def get_project_role_users(project_id: str, client: AuthenticatedClient):
    """Retrieve the users for a project.

    Args:
        project_id: The ID of the project.
        client: The authenticated client

    Returns:
        The users as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/{project_id}/users"),
        headers=authorization_header(client.token),
        timeout=constants.Hosting.TIMEOUT,
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json


def invite_user_to_project(
    role_id: str, user_id: str, client: AuthenticatedClient
) -> str:
    """Invite a user to a project with a specific role.

    Args:
        role_id: The ID of the role to assign to the user.
        user_id: The ID of the user to invite.
        client: The authenticated client

    Returns:
        The response from the invite operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/project/users/invite"),
        headers=authorization_header(client.token),
        json={"user_id": user_id, "role_id": role_id},
        timeout=constants.Hosting.TIMEOUT,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            return ex.response.json().get("detail")
        except json.JSONDecodeError:
            return ex.response.text
    return response.json()


def validate_deployment_args(
    app_name: str,
    project_id: str | None,
    regions: List[str] | None,
    vmtype: str | None,
    hostname: str | None,
    client: AuthenticatedClient,
) -> str:
    """Validate the deployment arguments.

    Args:
        app_name: The name of the application.
        project_id: The ID of the project to associate the deployment with.
        regions: The list of regions for the deployment.
        vmtype: The VM type for the deployment.
        hostname: The hostname for the deployment.
        client: The authenticated client.

    Returns:
        The validation result as a string -- "success" if all checks pass.

    """
    if not isinstance(client, AuthenticatedClient):
        return "not authenticated"

    param_data = {
        "app_name": app_name or "",
        "project_id": project_id or "",
        "regions": json.dumps(regions or []),
        "vmtype": vmtype or "",
        "hostname": hostname or "",
    }
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, "/v1/deployments/validate_cli"),
        headers=authorization_header(client.token),
        params=param_data,
        timeout=15,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            ex_details = ex.response.json().get("detail")
            return f"deployment failed: {ex_details}"
        except (httpx.RequestError, ValueError, KeyError):
            return "deployment failed: internal server error"

    return "success"


def create_deployment(
    app_name: str,
    project_id: str | None,
    regions: list | None,
    zip_dir: str,
    hostname: str | None,
    vmtype: str | None,
    secrets: dict | None,
    client: AuthenticatedClient,
    packages: list | None,
) -> str:
    """Create a new deployment for an application.

    Args:
        app_name: The name of the application.
        project_id: The ID of the project to associate the deployment with.
        regions: The list of regions for the deployment.
        zip_dir: The directory containing the zip files for the deployment.
        hostname: The hostname for the deployment.
        vmtype: The VM type for the deployment.
        secrets: The secrets to use for the deployment.
        client: The authenticated client
        packages: The list of packages to install on the VM.

    Returns:
        The deployment id.git c

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    cli_version = importlib.metadata.version("reflex-hosting-cli")
    zips = [
        (
            "files",
            (
                "backend.zip",
                open(os.path.join(zip_dir, "backend.zip"), "rb"),  # noqa: SIM115
            ),
        ),
        (
            "files",
            (
                "frontend.zip",
                open(os.path.join(zip_dir, "frontend.zip"), "rb"),  # noqa: SIM115
            ),
        ),
    ]
    payload: Dict[str, Any] = {
        "app_name": app_name,
        "reflex_hosting_cli_version": cli_version,
        "reflex_version": dependency.get_reflex_version(),
        "python_version": platform.python_version(),
    }
    if project_id:
        payload["project_id"] = project_id
    if regions:
        regions = regions if regions else []
        payload["regions"] = json.dumps(regions)
    if hostname:
        payload["hostname"] = hostname
    if vmtype:
        payload["vm_type"] = vmtype
    if secrets:
        payload["secrets"] = json.dumps(secrets)
    if packages:
        payload["packages"] = json.dumps(packages)

    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/deployments"),
        data=payload,
        files=zips,
        headers=authorization_header(client.token),
        timeout=55,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        try:
            ex_details = ex.response.json().get("detail")
            return f"deployment failed: {ex_details}"
        except (httpx.RequestError, ValueError, KeyError):
            return "deployment failed: internal server error"
    return response.json()


def stop_app(app_id: str, client: AuthenticatedClient):
    """Stop a running application.

    Args:
        app_id: The ID of the application.
        client: The authenticated client

    Returns:
        The response from the stop operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}/stop"),
        headers=authorization_header(client.token),
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        return f"stop app failed: {ex_details}"
    return response.json()


def start_app(app_id: str, client: AuthenticatedClient):
    """Start a stopped application.

    Args:
        app_id: The ID of the application.
        client: The authenticated client

    Returns:
        The response from the start operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}/start"),
        headers=authorization_header(client.token),
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        return f"start app failed: {ex_details}"
    return response.json()


def delete_app(app_id: str, client: AuthenticatedClient):
    """Delete an application.

    Args:
        app_id: The ID of the application.
        client: The authenticated client

    Returns:
        The response from the delete operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    app = get_app(app_id=app_id, client=client)
    if not app:
        console.warn("no app with given id found")
        return
    response = httpx.delete(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app['id']}/delete"),
        headers=authorization_header(client.token),
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        return f"delete app failed: {ex_details}"
    return response.json()


def get_app_logs(
    app_id: str,
    offset: int | None,
    start: int | None,
    end: int | None,
    client: AuthenticatedClient,
):
    """Retrieve logs for a given application.

    Args:
        app_id: The ID of the application.
        offset: The offset in seconds from the current time.
        start: The start time in Unix epoch format.
        end: The end time in Unix epoch format.
        client: The authenticated client

    Returns:
        The logs as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    app = get_app(app_id=app_id, client=client)
    if not app:
        console.warn("no app with given id found")
        return
    params = f"?offset={offset}" if offset else f"?start={start}&end={end}"
    try:
        response = httpx.get(
            urljoin(
                constants.Hosting.HOSTING_SERVICE,
                f"/v1/apps/{app['id']}/logsv2{params}",
            ),
            headers=authorization_header(client.token),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        return f"get app logs failed: {ex_details}"
    return response.json()


def list_apps(client: AuthenticatedClient, project: str | None = None) -> List[dict]:
    """List all the hosted deployments of the authenticated user.

    Args:
        project: The project ID to filter deployments.
        client: The authenticated client

    Returns:
        List[dict]: A list of deployments as dictionaries.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        Exception: when listing apps fails.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")

    url = urljoin(
        constants.Hosting.HOSTING_SERVICE,
        f"/v1/apps?project={project}" if project else "/v1/apps",
    )

    response = httpx.get(url, headers=authorization_header(client.token), timeout=5)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        raise Exception(f"list app failed: {ex_details}") from ex
    return response.json()


def get_app_history(app_id: str, client: AuthenticatedClient) -> list:
    """Retrieve the deployment history for a given application.

    Args:
        app_id: The ID of the application.
        client: The authenticated client

    Returns:
        list: A list of deployment history entries as dictionaries.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}/history"),
        headers=authorization_header(client.token),
    )

    response.raise_for_status()
    result = []
    response_json = response.json()
    for deployment in response_json:
        result.append(
            {
                "id": deployment["id"],
                "status": deployment["status"],
                "hostname": deployment["hostname"],
                "python version": deployment["python_version"],
                "reflex version": deployment["reflex_version"],
                "vm type": deployment["vm_type"],
                "timestamp": deployment["timestamp"],
            }
        )
    return result


def get_app_status(app_id: str, client: AuthenticatedClient) -> str:
    """Retrieve the status of a specific app.

    Args:
        app_id: The ID of the app.
        client: The authenticated client

    Returns:
        str: The status of the app.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    try:
        response = httpx.get(
            urljoin(
                constants.Hosting.HOSTING_SERVICE, f"/v1/deployments/{app_id}/status"
            ),
            headers=authorization_header(client.token),
        )
    except httpx.RequestError:
        return "lost connection: trying again"

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        return "error: bad response. received a bad response from cloud service."
    return response.json()


def scale_app(app_id, scale_params: ScaleParams, client: AuthenticatedClient):
    """Scale an application.

    Args:
        app_id: The ID of the application.
        scale_params: The scaling parameters.
        client: The authenticated client

    Returns:
        The response from the scale operation as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.
        ResponseError: If the request to scale the app fails.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.post(
        urljoin(constants.Hosting.HOSTING_SERVICE, f"/v1/apps/{app_id}/scale"),
        headers=authorization_header(client.token),
        json=scale_params.as_json(),
        timeout=constants.Hosting.TIMEOUT,
    )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        raise ResponseError(f"scale app failed: {ex_details}") from ex
    return response.json()


def get_deployment_status(deployment_id: str, client: AuthenticatedClient) -> str:
    """Retrieve the status of a specific deployment.

    Args:
        deployment_id: The ID of the deployment.
        client: The authenticated client

    Returns:
        str: The status of the deployment.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(
            constants.Hosting.HOSTING_SERVICE, f"/v1/deployments/{deployment_id}/status"
        ),
        headers=authorization_header(client.token),
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as ex:
        ex_details = ex.response.json().get("detail")
        return f"get status failed: {ex_details}"
    return response.json()


def _get_deployment_status(deployment_id: str, token: str) -> str:
    """Retrieve the status of a specific deployment with error handling.

    Args:
        deployment_id: The ID of the deployment.
        token: The authentication token.

    Returns:
        str: The status of the deployment, or an error message if the request fails.

    """
    try:
        response = httpx.get(
            urljoin(
                constants.Hosting.HOSTING_SERVICE,
                f"/v1/deployments/{deployment_id}/status",
            ),
            headers=authorization_header(token),
        )
    except httpx.RequestError:
        return "lost connection: trying again"

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        return "bad response. received a bad response from cloud service."
    return response.json()


def watch_deployment_status(deployment_id: str, client: AuthenticatedClient) -> bool:
    """Continuously watch the status of a specific deployment.

    Args:
        deployment_id: The ID of the deployment.
        client: The authenticated client

    Returns:
        True when the watching ends.
        False when watching ends in fail.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    with console.status("listening to status updates!"):
        current_status = ""
        while True:
            status = _get_deployment_status(
                deployment_id=deployment_id, token=client.token
            )
            if "completed successfully" in status:
                console.success(status)
                break
            if "build error" in status:
                console.warn(status)
                console.warn(
                    f"to see the build logs:\n reflex cloud apps build-logs {deployment_id}"
                )
                return False
            if "unable to find status for given id" in status:
                console.error(status)
                return False
            if "error" in status:
                console.warn(status)
                return False
            if "bad response" in status:
                console.warn(status)
                return True
            if status == current_status:
                continue
            current_status = status
            console.info(status)
            time.sleep(0.5)
    return True


def get_deployment_build_logs(deployment_id: str, client: AuthenticatedClient):
    """Retrieve the build logs for a specific deployment.

    Args:
        deployment_id: The ID of the deployment.
        client: The authenticated client

    Returns:
        dict: The build logs as a dictionary.

    Raises:
        NotAuthenticatedError: If the token is not valid.

    """
    if not isinstance(client, AuthenticatedClient):
        raise NotAuthenticatedError("not authenticated")
    response = httpx.get(
        urljoin(
            constants.Hosting.HOSTING_SERVICE,
            f"/v1/deployments/{deployment_id}/build/logs",
        ),
        headers=authorization_header(client.token),
    )

    response.raise_for_status()
    return response.json()


def list_projects():
    """List all projects.

    This function is currently a placeholder and does not perform any operations.

    Returns:
        None

    """
    return None


def fetch_token(request_id: str) -> str:
    """Fetch the access token for the request_id from Control Plane.

    Args:
        request_id: The request ID used when the user opens the browser for authentication.

    Returns:
        The access token if it exists, empty strings otherwise.

    """
    access_token = ""
    try:
        resp = httpx.get(
            urljoin(
                constants.Hosting.HOSTING_SERVICE, f"/v1/authenticate/{request_id}"
            ),
            timeout=constants.Hosting.TIMEOUT,
        )
        resp.raise_for_status()
        access_token = (resp_json := resp.json()).get("access_token", "")
        project_id = resp_json.get("user_id", "")
        select_project(project=project_id)
    except httpx.RequestError as re:
        console.debug(f"Unable to fetch token due to request error: {re}")
    except httpx.HTTPError as he:
        console.debug(f"Unable to fetch token due to {he}")
    except json.JSONDecodeError as jde:
        console.debug(f"Server did not respond with valid json: {jde}")
    except KeyError as ke:
        console.debug(f"Server response format unexpected: {ke}")
    except Exception as ex:
        console.debug(f"Unexpected errors: {ex}")

    return access_token


def authenticate_on_browser(invitation_code=None) -> tuple[str, dict[str, Any]]:
    """Open the browser to authenticate the user.

    Args:
        invitation_code: Used by the previous hosting service (ignored)

    Returns:
        The access token if valid and user information dict otherwise ("", {}).

    Raises:
        Exit: when the hosting service URL is invalid.

    """
    request_id = uuid.uuid4().hex
    auth_url = urljoin(
        constants.Hosting.HOSTING_SERVICE_UI, f"?request-id={request_id}"
    )

    console.print(f"Opening {auth_url} ...")

    if not is_valid_url(constants.Hosting.HOSTING_SERVICE_UI):
        console.error(
            f"Invalid hosting URL: {constants.Hosting.HOSTING_SERVICE_UI}. Ensure the URL is in the correct format and includes a valid scheme"
        )
        raise typer.Exit(1)

    if not webbrowser.open(auth_url):
        console.warn(
            f"Unable to automatically open the browser. Please go to {auth_url} to authenticate."
        )
    validated_info = {}
    access_token = ""
    console.ask("please hit 'Enter' or 'Return' after login on website complete")
    with console.status("Waiting for access token ..."):
        for _ in range(constants.Hosting.AUTH_RETRY_LIMIT):
            access_token = fetch_token(request_id)
            if access_token:
                break
            else:
                time.sleep(1)

    if access_token and (validated_info := validate_token_with_retries(access_token)):
        save_token_to_config(access_token)
    else:
        access_token = ""
    return access_token, validated_info


def validate_token_with_retries(access_token: str) -> dict[str, Any]:
    """Validate the access token without retries.

    Args:
        access_token: The access token to validate.

    Returns:
        validated user info dict.

    """
    with console.status("Validating access token ..."):
        try:
            return validate_token(access_token)
        except ValueError:
            console.error(f"Access denied")
            delete_token_from_config()
        except Exception as ex:
            console.debug(f"Unable to validate token due to: {ex}")
    return {}


def process_envs(envs: list[str]) -> dict[str, str]:
    """Process the environment variables.

    Args:
        envs: The environment variables expected in key=value format.

    Raises:
        SystemExit: If the envs are not in valid format.

    Returns:
        dict[str, str]: The processed environment variables in a dictionary.

    Raises:
        SystemExit: If invalid format.

    """
    processed_envs = {}
    for env in envs:
        kv = env.split("=", maxsplit=1)
        if len(kv) != 2:
            raise SystemExit("Invalid env format: should be <key>=<value>.")

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", kv[0]):
            raise SystemExit(
                "Invalid env name: should start with a letter or underscore, followed by letters, digits, or underscores."
            )
        processed_envs[kv[0]] = kv[1]
    return processed_envs


def read_config(path: str) -> dict:
    """Read the config file.

    Args:
        path: The path to the config file.

    Returns:
        dict: The config file as a dictionary.

    """
    try:
        with open(path, "r") as config_file:
            return yaml.safe_load(config_file)
    except Exception:
        return {}


def generate_config():
    """Generate the config file."""
    if os.path.exists("cloud.yml"):
        console.error("cloud.yml already exists.")
        return
    default = {
        "name": "default",
        "description": "",
        "regions": {"sjc": 1},
        "vmtype": "c1m1",
        "hostname": None,
        "envfile": ".env",
        "project": None,
        "packages": ["procps"],
    }
    with open("cloud.yml", "w") as config_file:
        yaml.dump(default, config_file, default_flow_style=False, sort_keys=False)
    console.success("cloud.yml created successfully.")
    return


def log_out_on_browser():
    """Open the browser to log out the user."""
    with contextlib.suppress(Exception):
        delete_token_from_config()
    console.print(f"Opening {constants.Hosting.HOSTING_SERVICE_UI} ...")
    if not webbrowser.open(constants.Hosting.HOSTING_SERVICE_UI):
        console.warn(
            f"Unable to open the browser automatically. Please go to {constants.Hosting.HOSTING_SERVICE_UI} to log out."
        )


def get_vm_types() -> list[dict]:
    """Retrieve the available VM types.

    Returns:
        list[dict]: A list of VM types as dictionaries.

    """
    try:
        response = httpx.get(
            urljoin(constants.Hosting.HOSTING_SERVICE, "/v1/deployments/vm_types"),
            timeout=10,
        )
        response.raise_for_status()
        response_json = response.json()
        if response_json is None or not isinstance(response_json, list):
            console.error("Expect server to return a list ")
            return []
        if (
            response_json
            and response_json[0] is not None
            and not isinstance(response_json[0], dict)
        ):
            console.error("Expect return values are dict's")
            return []
        return response_json
    except Exception as ex:
        console.error(f"Unable to get vmtypes due to {ex}.")
        return []


def get_regions() -> list[dict]:
    """Get the supported regions from the hosting server.

    Returns:
        list[dict]: A list of dict representation of the region information.

    """
    try:
        response = httpx.get(
            urljoin(constants.Hosting.HOSTING_SERVICE, "/v1/deployments/regions"),
            timeout=10,
        )
        response.raise_for_status()
        response_json = response.json()
        if response_json is None or not isinstance(response_json, list):
            console.error("Expect server to return a list ")
            return []
        if (
            response_json
            and response_json[0] is not None
            and not isinstance(response_json[0], dict)
        ):
            console.error("Expect return values are dict's")
            return []
        result = []
        for region in response_json:
            result.append({"name": region["name"], "code": region["code"]})
        return result
    except Exception as ex:
        console.error(f"Unable to get regions due to {ex}.")
        return []
