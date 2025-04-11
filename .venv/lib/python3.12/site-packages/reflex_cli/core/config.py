"""Module for the Config class."""

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic.v1 import BaseModel, ValidationError

from reflex_cli import constants
from reflex_cli.utils.exceptions import ConfigError, ConfigInvalidFieldValueError

RegionOption = Literal[
    "ams",
    "arn",
    "atl",
    "bog",
    "bom",
    "bos",
    "cdg",
    "den",
    "dfw",
    "ewr",
    "eze",
    "fra",
    "gdl",
    "gig",
    "gru",
    "hkg",
    "iad",
    "jnb",
    "lax",
    "lhr",
    "mad",
    "mia",
    "nrt",
    "ord",
    "otp",
    "phx",
    "qro",
    "scl",
    "sea",
    "sin",
    "sjc",
    "syd",
    "waw",
    "yul",
    "yyz",
]

VmType = Literal[
    "c1m.5",
    "c1m1",
    "c1m2",
    "c2m.5",
    "c2m1",
    "c2m2",
    "c2m4",
    "c4m1",
    "c4m2",
    "c4m4",
    "c4m8",
]

ScaleType = Literal["region", "size"]


class Config(BaseModel):  # pyright: ignore [reportUnboundVariable]
    """Configuration class for the CLI."""

    name: Optional[str] = None
    description: Optional[str] = None
    vmtype: Optional[VmType] = None
    regions: Optional[dict[RegionOption, int]] = None
    hostname: Optional[str] = None
    envfile: str = ".env"
    project: Optional[str] = None
    packages: list[str] = []
    _cloud_yaml_path: Path = Path.cwd() / constants.Dirs.CLOUD

    class Config:
        """Pydantic config."""

        arbitrary_types_allowed = True
        use_enum_values = True

    def __init__(self, **kwargs):
        """Initialize the Config instance.

        Args:
            **kwargs: Key-value pairs of fields to initialize the Config instance.

        Raises:
            ConfigInvalidFieldValueError: If an invalid value is provided for a config field.

        """
        try:
            super().__init__(**kwargs)
        except ValidationError as e:
            errors = e.errors()[0]
            field = errors["loc"][0]
            given = errors.get("ctx", {}).get("given", "")
            supported = ", ".join(errors.get("ctx", {}).get("permitted", []))
            raise ConfigInvalidFieldValueError(
                f"Invalid value {given} for  {field} in cloud.yml. Supported values are {supported}"
            ) from None

    @classmethod
    def from_yaml(cls, yaml_path: Path = Path.cwd() / constants.Dirs.CLOUD) -> "Config":
        """Creates a Config instance from a YAML file.

        Args:
            yaml_path: The path to the YAML file. Defaults to "cloud.yml" in the current directory.

        Returns:
            Config: A Config instance with the values from the YAML file.

        Raises:
            ConfigError: If the YAML file is not found.

        """
        try:
            with open(yaml_path, "r") as file:
                data = yaml.safe_load(file)
            return cls(_cloud_yaml_path=yaml_path, **data)
        except FileNotFoundError as e:
            raise ConfigError(f"Config file not found at {yaml_path}.") from e

    @classmethod
    def from_yaml_or_default(
        cls, yaml_path: Path = Path.cwd() / constants.Dirs.CLOUD
    ) -> "Config":
        """Creates a Config instance from a YAML file or returns a default instance.

        Args:
            yaml_path: The path to the YAML file. Defaults to "cloud.yml" in the current directory.

        Returns:
            Config: A Config instance with the values from the YAML file or a default instance.

        """
        try:
            return cls.from_yaml(yaml_path)

        except ConfigError:
            return cls()

    def with_overrides(self, **kwargs: Any) -> "Config":
        """Creates a new Config instance with overrides.

        Args:
            **kwargs: Key-value pairs of fields to override. The values take
                      precedence over the existing instance values.

        Returns:
            Config: A new Config instance with updated values.

        """
        updated_values = {
            field: (
                kwargs[field]
                if field in kwargs and kwargs[field]
                else getattr(self, field)
            )
            for field in self.__fields__
        }
        return Config(**updated_values)

    def exists(self) -> bool:
        """Check if the config file exists.

        Returns:
            bool: True if the config file exists, False otherwise.

        """
        return self._cloud_yaml_path.exists()
