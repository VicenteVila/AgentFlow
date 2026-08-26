"""Shared pytest configuration: --update-golden flag for byte-exact fixtures."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden fixture files instead of comparing against them",
    )
