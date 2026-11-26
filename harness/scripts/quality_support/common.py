"""Shared diagnostics for the harness quality CLI."""
from __future__ import annotations


class QualityError(Exception):
    """An expected refusal or operational error suitable for a concise diagnostic."""


def require(condition, message):
    if not condition:
        raise QualityError(message)
