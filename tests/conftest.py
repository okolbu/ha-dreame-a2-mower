"""Shared test fixtures for dreame_a2_mower protocol tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
from types import ModuleType

import pytest


class MockModuleLoader:
    """Loads mock modules to avoid importing heavy dependencies during testing."""

    def __init__(self):
        self.mocked_modules = set()

    def mock_module(self, module_path: str) -> MagicMock:
        """Create and register a mock module."""
        if module_path in sys.modules:
            return sys.modules[module_path]

        parts = module_path.split(".")
        mock_module = MagicMock()

        # Install all parent modules and this module
        for i in range(1, len(parts) + 1):
            parent_path = ".".join(parts[:i])
            if parent_path not in sys.modules:
                sys.modules[parent_path] = MagicMock()
                self.mocked_modules.add(parent_path)

        return sys.modules[module_path]

    def mock_modules(self, module_list: list[str]) -> None:
        """Mock a list of modules."""
        for module_path in module_list:
            self.mock_module(module_path)


# Initialize mock loader and mock all heavy external dependencies
_loader = MockModuleLoader()

# Mock all dependencies needed by the component
_external_modules = [
    # Home Assistant
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.components",
    "homeassistant.components.frontend",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    # Numeric & image processing
    "numpy",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    # Network & protocol
    "bleak",
    "requests",
    "paho",
    "paho.mqtt",
    "paho.mqtt.client",
    # Encryption
    "cryptography",
    "cryptography.hazmat",
    "cryptography.hazmat.backends",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.ciphers",
    "cryptography.hazmat.primitives.ciphers.algorithms",
    "Crypto",
    "Crypto.Cipher",
    "Crypto.Random",
    "Crypto.Util",
    "Crypto.Util.Padding",
    # Xiaomi Mi IO
    "miio",
    "miio.miioprotocol",
    # JavaScript/V8
    "py_mini_racer",
]

_loader.mock_modules(_external_modules)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures directory."""
    return FIXTURES
