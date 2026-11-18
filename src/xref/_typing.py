"""Narrow untyped JSON and YAML values to concrete types."""

from __future__ import annotations

from typing import Any, cast


def as_mapping(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def as_list(value: object) -> list[Any] | None:
    return cast(list[Any], value) if isinstance(value, list) else None
