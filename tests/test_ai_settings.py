from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from xp.config import XPConfig


class AISettingsTests(unittest.TestCase):
    def _module(self):
        try:
            return importlib.import_module("xp.ai.settings")
        except ModuleNotFoundError:
            self.fail("xp.ai.settings must exist for AF-02 Task 2")

    @staticmethod
    def _valid_data():
        return {
            "version": 1,
            "default_route": "9router-gemini",
            "routes": {
                "9router-gemini": {
                    "transport": "openai-compatible",
                    "base_url": "http://127.0.0.1:20128/v1/",
                    "model": "gemini/gemini-3.5-flash-lite",
                    "secret_env": "NINEROUTER_KEY",
                    "cost_class": "free",
                }
            },
        }

    def _settings_error(self):
        module = self._module()
        return module.AISettingsError

    def test_valid_route_is_parsed_and_base_url_is_normalized(self):
        module = self._module()
        settings = module.AISettings.from_dict(self._valid_data())

        route = settings.route()
        self.assertEqual(route.route_id, "9router-gemini")
        self.assertEqual(route.transport, "openai-compatible")
        self.assertEqual(route.base_url, "http://127.0.0.1:20128/v1")
        self.assertEqual(route.model, "gemini/gemini-3.5-flash-lite")
        self.assertEqual(route.secret_env, "NINEROUTER_KEY")
        self.assertEqual(route.cost_class, "free")

    def test_explicit_route_lookup_returns_named_route(self):
        module = self._module()
        data = self._valid_data()
        data["routes"]["backup"] = {
            "transport": "openai-compatible",
            "base_url": "https://example.invalid/v1",
            "model": "example/model",
            "secret_env": "BACKUP_AI_KEY",
            "cost_class": "unknown",
        }

        settings = module.AISettings.from_dict(data)

        self.assertEqual(settings.route("backup").route_id, "backup")

    def test_invalid_version_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data["version"] = 2

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_missing_default_route_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data.pop("default_route")

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_default_route_must_exist_in_routes(self):
        module = self._module()
        data = self._valid_data()
        data["default_route"] = "missing"

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_empty_model_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data["routes"]["9router-gemini"]["model"] = " "

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_invalid_base_url_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data["routes"]["9router-gemini"]["base_url"] = "file:///tmp/model"

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_invalid_secret_env_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data["routes"]["9router-gemini"]["secret_env"] = "BAD-KEY"

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_invalid_cost_class_is_rejected(self):
        module = self._module()
        data = self._valid_data()
        data["routes"]["9router-gemini"]["cost_class"] = "maybe"

        with self.assertRaises(module.AISettingsError):
            module.AISettings.from_dict(data)

    def test_unknown_route_lookup_is_rejected(self):
        module = self._module()
        settings = module.AISettings.from_dict(self._valid_data())

        with self.assertRaises(module.AISettingsError):
            settings.route("missing")

    def test_from_file_reads_non_secret_configuration(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ai.json"
            path.write_text(
                json.dumps(self._valid_data()),
                encoding="utf-8",
            )

            settings = module.AISettings.from_file(path)

        self.assertEqual(settings.default_route, "9router-gemini")

    def test_for_home_uses_expert_workstation_config_without_creating_it(self):
        module = self._module()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            target = home / ".expert-workstation" / "config" / "ai.json"

            with self.assertRaises(module.AISettingsError):
                module.AISettings.for_home(home)

            self.assertFalse(target.exists())

            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(self._valid_data()),
                encoding="utf-8",
            )

            settings = module.AISettings.for_home(home)

        self.assertEqual(settings.default_route, "9router-gemini")

    def test_environment_secret_value_is_not_stored_or_rendered(self):
        module = self._module()
        secret_marker = "unit-test-secret-marker-not-for-storage"

        with patch.dict(
            os.environ,
            {"NINEROUTER_KEY": secret_marker},
            clear=False,
        ):
            settings = module.AISettings.from_dict(self._valid_data())

        rendered = repr(settings)
        self.assertNotIn(secret_marker, rendered)
        self.assertEqual(settings.route().secret_env, "NINEROUTER_KEY")

    def test_xp_config_schema_remains_unchanged(self):
        self.assertEqual(
            [field.name for field in fields(XPConfig)],
            ["home", "device_id", "control_repo"],
        )


if __name__ == "__main__":
    unittest.main()
