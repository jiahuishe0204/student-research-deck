"""Unique SCF entrypoint for the production task HTTP control plane."""

from __future__ import annotations

from delivery_http_entrypoint import main_handler as _delivery_main_handler


def main_handler(event, context=None):
    """Forward the SCF HTTP event to the shared authenticated API handler."""
    return _delivery_main_handler(event, context)


__all__ = ["main_handler"]
