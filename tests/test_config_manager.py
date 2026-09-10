import json
import os
import tempfile
import unittest

from config_manager import (
    ConfigConflictError,
    ConfigManager,
    ConfigValidationError,
)


class ConfigManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")
        self.manager = ConfigManager(self.config_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_config_is_valid_and_written(self):
        config, revision = self.manager.reload_config()

        self.assertEqual(config["group_configs"][0]["group_id"], "12345678")
        self.assertEqual(len(revision), 64)
        with open(self.config_path, encoding="utf-8") as config_file:
            self.assertIsInstance(json.load(config_file), dict)

    def test_nested_config_and_unknown_fields_are_preserved(self):
        config, revision = self.manager.reload_config()
        config["future_root_field"] = {"enabled": True}
        config["group_configs"][0]["future_group_field"] = "keep-me"
        config["group_configs"][0]["servers"][0]["future_server_field"] = 42

        saved, _ = self.manager.replace_config(config, revision)

        self.assertEqual(saved["future_root_field"], {"enabled": True})
        self.assertEqual(
            saved["group_configs"][0]["servers"][0]["future_server_field"], 42
        )

    def test_stale_revision_is_rejected(self):
        config, revision = self.manager.reload_config()
        config["safeMode"] = True
        self.manager.replace_config(config, revision)

        config["safeMode"] = False
        with self.assertRaises(ConfigConflictError):
            self.manager.replace_config(config, revision)

    def test_duplicate_groups_and_invalid_ports_are_rejected(self):
        config = ConfigManager.default_config()
        config["group_configs"].append(
            {
                "group_id": "12345678",
                "hh_room_id": "",
                "admin_users": [],
                "servers": [],
            }
        )
        with self.assertRaisesRegex(ConfigValidationError, "群组 ID .*重复"):
            ConfigManager.validate_config(config)

        config = ConfigManager.default_config()
        config["group_configs"][0]["servers"][0]["address"] = "localhost:70000"
        with self.assertRaisesRegex(ConfigValidationError, "端口必须"):
            ConfigManager.validate_config(config)


if __name__ == "__main__":
    unittest.main()
