from unittest.mock import patch

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestGetTestTagsFromModules(RunbotCase):
    """Tests for RunbotBuild._get_test_tags_from_modules"""

    def setUp(self):
        super().setUp()

        # Build params linked to trigger_addons (repo_addons + dependency repo_server)
        self.server_commit = self.Commit.create(
            {
                "name": "aaaa0000ffffffffffffffffffffffffffff0000",
                "tree_hash": "0aaaa0000ffffffffffffffffffffffffffff000",
                "repo_id": self.repo_server.id,
            }
        )
        self.addons_commit = self.Commit.create(
            {
                "name": "bbbb0000ffffffffffffffffffffffffffff0000",
                "tree_hash": "0bbbb0000ffffffffffffffffffffffffffff000",
                "repo_id": self.repo_addons.id,
            }
        )
        self.params = self.base_params.copy(
            {
                "trigger_id": self.trigger_addons.id,
                "commit_link_ids": [
                    (0, 0, {"commit_id": self.server_commit.id}),
                    (0, 0, {"commit_id": self.addons_commit.id}),
                ],
            }
        )
        self.build = self.Build.create({"params_id": self.params.id})

        # Simulate available modules: repo_server has 'base','mail'; repo_addons has 'sale','account','stock'
        self._available_modules = {
            self.repo_server: ["base", "mail"],
            self.repo_addons: ["sale", "account", "stock"],
        }

    def _patch_available(self):
        available = self._available_modules
        return patch(
            "odoo.addons.runbot.models.build.BuildResult._get_available_modules",
            return_value=available,
        )

    # ------------------------------------------------------------------
    # No test_modules configured anywhere → all modules (same as native 'modules' field)
    # ------------------------------------------------------------------
    def test_no_patterns_returns_all_modules(self):
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/base", "/mail", "/sale", "/stock"])

    # ------------------------------------------------------------------
    # Positive-only pattern → adds to full set (no-op if already present)
    # To select a subset, use '-*,module' idiom
    # ------------------------------------------------------------------
    def test_positive_pattern_does_not_filter(self):
        # 'sale' alone does NOT restrict to sale — it adds sale to the already-full set
        self.repo_addons.test_modules = "sale"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/base", "/mail", "/sale", "/stock"])

    # ------------------------------------------------------------------
    # '-*,module' idiom → select only specific modules
    # ------------------------------------------------------------------
    def test_select_subset_with_exclude_all_then_include(self):
        self.repo_addons.test_modules = "-*,sale,account"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/base", "/mail", "/sale"])

    # ------------------------------------------------------------------
    # Wildcard '*' → same result as empty (adds everything to full set)
    # ------------------------------------------------------------------
    def test_wildcard_star_returns_all_modules(self):
        self.repo_addons.test_modules = "*"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/base", "/mail", "/sale", "/stock"])

    # ------------------------------------------------------------------
    # Exclusion pattern → removes from full set
    # ------------------------------------------------------------------
    def test_exclusion_pattern(self):
        self.repo_addons.test_modules = "-stock"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/base", "/mail", "/sale"])

    # ------------------------------------------------------------------
    # Pattern that resolves to nothing → [] (no injection)
    # ------------------------------------------------------------------
    def test_all_excluded_returns_empty(self):
        self.repo_server.test_modules = "-*"
        self.repo_addons.test_modules = "-*"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(tags, [])

    # ------------------------------------------------------------------
    # Each repo's result is independent and unioned
    # ------------------------------------------------------------------
    def test_per_repo_results_are_unioned(self):
        # Select only 'base' from server, only 'sale' from addons
        self.repo_server.test_modules = "-*,base"
        self.repo_addons.test_modules = "-*,sale"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/base", "/sale"])

    # ------------------------------------------------------------------
    # Dependency repo patterns are also applied
    # ------------------------------------------------------------------
    def test_dependency_repo_patterns_applied(self):
        # repo_server is in dependency_ids of trigger_addons
        self.repo_server.test_modules = "-*,mail"
        with self._patch_available():
            tags = self.build._get_test_tags_from_modules()
        self.assertEqual(sorted(tags), ["/account", "/mail", "/sale", "/stock"])
