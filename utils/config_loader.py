import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """Recursively replace ``${VAR_NAME}`` placeholders with environment variable values.

    Variables must have the prefix CHECK_TOOL (convention, not enforced here).
    Raises ``EnvironmentError`` if a referenced variable is not set.
    """
    if isinstance(value, str):
        def _sub(match: re.Match) -> str:
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                raise EnvironmentError(
                    f"Environment variable '{var}' referenced in config is not set. "
                    "Variables should have the CHECK_TOOL_ prefix."
                )
            return val
        return _ENV_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load, parse and resolve ``${ENV_VAR}`` placeholders in a YAML config."""
    with open(config_path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    return _resolve_env_vars(config or {})
