from unittest.mock import patch

from odoo.addons.runbot.container import Command
from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged

# Available modules for integration tests
_AVAILABLE_MODULES = None  # set per-test via _patch_available


def _make_cmd(*args):
    return Command([], list(args), [])


@tagged("-at_install", "post_install")
class TestRunInstallOdoo(RunbotCase):
    """Tests for RunbotBuildConfigStep._run_install_odoo injection of dynamic test tags."""

    def setUp(self):
        super().setUp()
        self.step = self.Step.create({"name": "test_step", "job_type": "install_odoo", "test_enable": True})

        server_commit = self.Commit.create(
            {
                "name": "aaaa0000ffffffffffffffffffffffffffff0000",
                "tree_hash": "0aaaa0000ffffffffffffffffffffffffffff000",
                "repo_id": self.repo_server.id,
            }
        )
        addons_commit = self.Commit.create(
            {
                "name": "bbbb0000ffffffffffffffffffffffffffff0000",
                "tree_hash": "0bbbb0000ffffffffffffffffffffffffffff000",
                "repo_id": self.repo_addons.id,
            }
        )
        params = self.base_params.copy(
            {
                "trigger_id": self.trigger_addons.id,
                "commit_link_ids": [
                    (0, 0, {"commit_id": server_commit.id}),
                    (0, 0, {"commit_id": addons_commit.id}),
                ],
            }
        )
        self.build = self.Build.create({"params_id": params.id})

    def _patch_super(self, cmd):
        """Mock the native _run_install_odoo to return a controlled Command."""
        return patch(
            "odoo.addons.runbot.models.build_config.ConfigStep._run_install_odoo",
            return_value={"cmd": cmd},
        )

    def _patch_dynamic_tags(self, tags):
        """Mock _get_test_tags_from_modules on the build instance."""
        return patch.object(
            type(self.build),
            "_get_test_tags_from_modules",
            return_value=tags,
        )

    def _get_test_tags_value(self, cmd):
        idx = cmd.cmd.index("--test-tags")
        return cmd.cmd[idx + 1]

    # ------------------------------------------------------------------
    # test_enable=False → no injection
    # ------------------------------------------------------------------
    def test_no_injection_when_test_enable_false(self):
        self.step.test_enable = False
        cmd = _make_cmd("odoo", "--test-enable", "--test-tags", "/sale,/account")
        with self._patch_super(cmd), self._patch_dynamic_tags(["/mod_a"]):
            res = self.step._run_install_odoo(self.build)
        self.assertEqual(self._get_test_tags_value(res["cmd"]), "/sale,/account")

    # ------------------------------------------------------------------
    # --test-tags already in cmd (from config step's test_tags field)
    # Dynamic tags are prepended; config step tags act as final filter
    # ------------------------------------------------------------------
    def test_dynamic_tags_prepended_before_config_step_tags(self):
        cmd = _make_cmd("odoo", "--test-enable", "--test-tags", "/sale,/account")
        dynamic = ["/ingadhoc_a", "/ingadhoc_b"]
        with self._patch_super(cmd), self._patch_dynamic_tags(dynamic):
            res = self.step._run_install_odoo(self.build)
        self.assertEqual(
            self._get_test_tags_value(res["cmd"]),
            "/ingadhoc_a,/ingadhoc_b,/sale,/account",
        )

    # ------------------------------------------------------------------
    # Only --test-enable in cmd (no test_tags on config step)
    # Dynamic tags are added as a new --test-tags argument
    # ------------------------------------------------------------------
    def test_dynamic_tags_added_when_no_test_tags_in_cmd(self):
        cmd = _make_cmd("odoo", "--test-enable")
        dynamic = ["/ingadhoc_a", "/ingadhoc_b"]
        with self._patch_super(cmd), self._patch_dynamic_tags(dynamic):
            res = self.step._run_install_odoo(self.build)
        self.assertIn("--test-tags", res["cmd"].cmd)
        self.assertEqual(self._get_test_tags_value(res["cmd"]), "/ingadhoc_a,/ingadhoc_b")

    # ------------------------------------------------------------------
    # Empty dynamic tags → no injection, cmd unchanged
    # ------------------------------------------------------------------
    def test_no_injection_when_dynamic_tags_empty(self):
        cmd = _make_cmd("odoo", "--test-enable")
        with self._patch_super(cmd), self._patch_dynamic_tags([]):
            res = self.step._run_install_odoo(self.build)
        self.assertNotIn("--test-tags", res["cmd"].cmd)
