import configparser
import os
import tempfile
from unittest.mock import patch

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.exceptions import ValidationError
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestProjectProtectLiveBuilds(RunbotCase):
    def test_public_project_cannot_turn_off(self):
        self.assertTrue(self.project.protect_live_builds)
        with self.assertRaises(ValidationError):
            self.project.protect_live_builds = False

    def test_restricted_project_can_turn_off(self):
        self.project.group_ids = self.env.ref("runbot.group_user")
        self.project.protect_live_builds = False
        with self.assertRaises(ValidationError):
            self.project.group_ids = False

    def _protect(self, available_modules):
        build = self.Build.create({"params_id": self.base_params.id})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rc_path = os.path.join(tmp_dir, ".odoorc")
            with open(rc_path, "w") as rc_file:
                rc_file.write("[options]\nserver_wide_modules = base,web\n")
            with (
                patch("odoo.addons.runbot.models.build.BuildResult._path", return_value=rc_path),
                patch(
                    "odoo.addons.runbot.models.build.BuildResult._get_available_modules",
                    return_value={self.repo_addons: available_modules},
                ),
            ):
                build._protect_live_build()
            parser = configparser.RawConfigParser()
            parser.read(rc_path)
        return parser["options"]

    def test_guard_loaded_when_available(self):
        options = self._protect(["sale", "runbot_build_guard"])
        self.assertEqual(options["server_wide_modules"], "base,web,runbot_build_guard")
        self.assertEqual(options["list_db"], "False")

    def test_guard_skipped_when_missing(self):
        options = self._protect(["sale"])
        self.assertEqual(options["server_wide_modules"], "base,web")
        self.assertEqual(options["list_db"], "False")
