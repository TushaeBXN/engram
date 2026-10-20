"""Check tool arguments against the tool's own schema before it runs.

Every Engram tool (MCP and HTTP) declares an ``inputSchema``. Without a check,
a wrong argument reaches the tool as a Python error ("unexpected keyword
argument", or a string where a number was meant) and a client sees a stack of
internal detail. :func:`validate_arguments` turns those into one plain
message that names the parameter, and converts the harmless cases clients
commonly get wrong (``"5"`` for a number, ``"false"`` for a boolean).
"""

from __future__ import annotations

from typing import Any


class ArgumentError(ValueError):
    """The arguments do not match the tool's schema. The message names the parameter."""


_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def _coerce(name: str, value: Any, spec: dict) -> Any:
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise ArgumentError(f"'{name}' must be text")
    elif kind == "integer":
        if isinstance(value, bool):
            raise ArgumentError(f"'{name}' must be a whole number")
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                raise ArgumentError(f"'{name}' must be a whole number") from None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int):
            raise ArgumentError(f"'{name}' must be a whole number")
    elif kind == "number":
        if isinstance(value, bool):
            raise ArgumentError(f"'{name}' must be a number")
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                raise ArgumentError(f"'{name}' must be a number") from None
        if not isinstance(value, (int, float)):
            raise ArgumentError(f"'{name}' must be a number")
    elif kind == "boolean":
        if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
            value = value.strip().lower() in _TRUE
        if not isinstance(value, bool):
            raise ArgumentError(f"'{name}' must be true or false")
    elif kind == "array":
        if not isinstance(value, list):
            raise ArgumentError(f"'{name}' must be a list")
        item = spec.get("items")
        if item:
            value = [_coerce(f"{name}[{i}]", v, item) for i, v in enumerate(value)]
    elif kind == "object":
        if not isinstance(value, dict):
            raise ArgumentError(f"'{name}' must be an object")
    if "enum" in spec and value not in spec["enum"]:
        raise ArgumentError(f"'{name}' must be one of: {', '.join(map(str, spec['enum']))}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            raise ArgumentError(f"'{name}' must be at least {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise ArgumentError(f"'{name}' must be at most {spec['maximum']}")
    return value


def validate_arguments(schema: dict, arguments: Any, max_text: int = 1_000_000) -> dict:
    """Return *arguments* checked and converted against *schema* (a tool's ``inputSchema``).

    Raises :class:`ArgumentError` for: arguments that are not an object, a
    missing required parameter, a parameter the tool does not have, a wrong
    type, a value outside ``enum``/``minimum``/``maximum``, or text longer
    than *max_text* characters.
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ArgumentError("arguments must be an object")
    props = schema.get("properties", {})
    for name in arguments:  # a misspelt name is the likeliest mistake, so report it before "missing"
        if name not in props:
            known = ", ".join(props) or "none"
            raise ArgumentError(f"unknown parameter '{name}' (this tool takes: {known})")
    for name in schema.get("required", []):
        if name not in arguments or arguments[name] is None:
            raise ArgumentError(f"missing required parameter '{name}'")
    out = {}
    for name, value in arguments.items():
        if value is None:
            continue  # optional parameter left empty
        value = _coerce(name, value, props[name])
        if isinstance(value, str) and len(value) > max_text:
            raise ArgumentError(f"'{name}' is too long (limit {max_text:,} characters)")
        out[name] = value
    return out
