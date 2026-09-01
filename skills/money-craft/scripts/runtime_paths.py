#!/usr/bin/env python3
"""XDG-aware, repo-external runtime paths for Money Craft."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Mapping, MutableMapping

APP_NAME = "money-craft"
CONFIG_HOME_ENV = "MONEY_CRAFT_CONFIG_HOME"
DATA_HOME_ENV = "MONEY_CRAFT_DATA_HOME"
CACHE_HOME_ENV = "MONEY_CRAFT_CACHE_HOME"
ENV_FILE_ENV = "MONEY_CRAFT_ENV_FILE"
ENV_FILE_ACTIVE_ENV = "MONEY_CRAFT_ENV_FILE_ACTIVE"
DATA_PYTHON_ENV = "MONEY_CRAFT_DATA_PYTHON"
REPORT_PYTHON_ENV = "MONEY_CRAFT_REPORT_PYTHON"
OUTPUT_ROOT_ENV = "MONEY_CRAFT_OUTPUT_ROOT"
MAX_ENV_FILE_BYTES = 64 * 1024
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
ALLOWED_ENV_FILE_KEYS = {
    "FRED_API_KEY",
    "FUYAO_API_KEY",
    CONFIG_HOME_ENV,
    DATA_HOME_ENV,
    CACHE_HOME_ENV,
    DATA_PYTHON_ENV,
    REPORT_PYTHON_ENV,
    OUTPUT_ROOT_ENV,
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
}


class RuntimePathError(ValueError):
    """Raised when a runtime path or explicit env file is unsafe or invalid."""


def _environment(environment: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environment is None else environment


def _home(home: Path | None) -> Path:
    return (Path.home() if home is None else home).expanduser().resolve()


def _absolute_override(environment: Mapping[str, str], name: str) -> Path | None:
    value = environment.get(name, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimePathError(f"{name} must be an absolute path")
    return path.resolve(strict=False)


def config_home(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    environ = _environment(environment)
    explicit = _absolute_override(environ, CONFIG_HOME_ENV)
    if explicit is not None:
        return explicit, f"environment:{CONFIG_HOME_ENV}"
    xdg = _absolute_override(environ, "XDG_CONFIG_HOME")
    if xdg is not None:
        return xdg / APP_NAME, "environment:XDG_CONFIG_HOME"
    return _home(home) / ".config" / APP_NAME, "default"


def data_home(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    environ = _environment(environment)
    explicit = _absolute_override(environ, DATA_HOME_ENV)
    if explicit is not None:
        return explicit, f"environment:{DATA_HOME_ENV}"
    xdg = _absolute_override(environ, "XDG_DATA_HOME")
    if xdg is not None:
        return xdg / APP_NAME, "environment:XDG_DATA_HOME"
    return _home(home) / ".local" / "share" / APP_NAME, "default"


def cache_home(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    environ = _environment(environment)
    explicit = _absolute_override(environ, CACHE_HOME_ENV)
    if explicit is not None:
        return explicit, f"environment:{CACHE_HOME_ENV}"
    xdg = _absolute_override(environ, "XDG_CACHE_HOME")
    if xdg is not None:
        return xdg / APP_NAME, "environment:XDG_CACHE_HOME"
    return _home(home) / ".cache" / APP_NAME, "default"


def config_file(
    filename: str,
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    root, _source = config_home(environment, home=home)
    return root / filename


def display_path(path: Path, *, home: Path | None = None) -> str:
    resolved_home = _home(home)
    try:
        relative = path.relative_to(resolved_home)
    except ValueError:
        return str(path)
    return f"~/{relative.as_posix()}"


def preferred_runtime_python(
    kind: str,
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    if kind not in {"data", "report"}:
        raise RuntimePathError(f"unsupported runtime kind: {kind}")
    environ = _environment(environment)
    override_name = DATA_PYTHON_ENV if kind == "data" else REPORT_PYTHON_ENV
    configured = _absolute_override(environ, override_name)
    if configured is not None:
        return configured, f"environment:{override_name}"

    root, source = data_home(environ, home=home)
    preferred = root / "venvs" / kind / "bin" / "python"
    legacy = _home(home) / ".config" / APP_NAME / f"{kind}-venv" / "bin" / "python"
    if source == "default" and not preferred.is_file() and legacy.is_file():
        return legacy, "legacy-fallback"
    return preferred, source


def _parse_env_value(raw: str, *, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise RuntimePathError(f"invalid quoted value on env file line {line_number}")
        value = value[1:-1]
    if "\x00" in value or "\r" in value or "\n" in value:
        raise RuntimePathError(f"invalid control character on env file line {line_number}")
    return value


def load_explicit_env_file(environment: MutableMapping[str, str] | None = None) -> Path | None:
    """Load an explicitly selected, permission-restricted dotenv file.

    Existing process variables win. The parser deliberately supports only a
    small key=value subset and a Money Craft allowlist; it never executes shell
    syntax, interpolates values, or searches parent directories.
    """

    environ = os.environ if environment is None else environment
    path = _absolute_override(environ, ENV_FILE_ENV)
    if path is None:
        return None
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimePathError(f"{ENV_FILE_ENV} does not exist") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimePathError(f"{ENV_FILE_ENV} must select a regular file, not a symlink")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise RuntimePathError(f"{ENV_FILE_ENV} must select a file owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimePathError(f"{ENV_FILE_ENV} file permissions must be 0600 or stricter")
    if metadata.st_size < 1 or metadata.st_size > MAX_ENV_FILE_BYTES:
        raise RuntimePathError(f"{ENV_FILE_ENV} file has an invalid size")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimePathError(f"cannot read {ENV_FILE_ENV}") from exc
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RuntimePathError(f"env file line {line_number} must use KEY=VALUE")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not ENV_NAME_RE.fullmatch(key) or key not in ALLOWED_ENV_FILE_KEYS:
            raise RuntimePathError(f"env file line {line_number} uses unsupported key {key!r}")
        value = _parse_env_value(raw_value, line_number=line_number)
        if value and not environ.get(key):
            environ[key] = value
    environ[ENV_FILE_ACTIVE_ENV] = str(path)
    return path
