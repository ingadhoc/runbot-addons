from unittest.mock import patch

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestCreatePostInstallChildren(RunbotCase):
    """Tests for RunbotBuild._create_post_install_children and _split_test_tags"""

    def setUp(self):
        super().setUp()
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

        # The last install step of the config: where the children take the
        # database and the tags from.
        self.install_step = self.env.ref("runbot.runbot_build_config_step_test_all")
        self.install_step.test_tags = "/analytic,/uom,-.test_broken,-post_install"

        self._available_modules = {
            self.repo_server: ["base"],
            self.repo_addons: ["sale", "account", "stock"],
        }

    def _patch_available(self):
        return patch(
            "odoo.addons.runbot.models.build.BuildResult._get_available_modules",
            return_value=self._available_modules,
        )

    def _tags_of(self, build):
        return build.params_id.config_data["test_tags"].split(",")

    def test_tags_are_split_once_and_excluded_ones_go_to_every_child(self):
        with self._patch_available():
            self.build._create_post_install_children(2)

        children = self.build.children_ids
        self.assertEqual(len(children), 2)
        tags = [self._tags_of(child) for child in children]
        for child_tags in tags:
            self.assertIn("-.test_broken", child_tags, "a test that is off has to stay off in every child")
        included = sorted(tag for child_tags in tags for tag in child_tags if not tag.startswith("-"))
        self.assertEqual(
            included,
            ["/account", "/analytic", "/base", "/sale", "/stock", "/uom"],
            "the modules of the repos plus the positive tags of the step, each in one child only",
        )

    def test_the_phase_tag_of_the_parent_does_not_reach_the_children(self):
        with self._patch_available():
            self.build._create_post_install_children(1)

        # The parent skips post_install so the children can run it. If they
        # took that tag too, they would run nothing.
        self.assertNotIn("-post_install", self._tags_of(self.build.children_ids))

    def test_parts_are_balanced_with_the_recorded_times(self):
        self.env["runbot.build.stat"].create(
            {
                "build_id": self.build.id,
                "category": "test_time",
                "values": {"sale": 100, "account": 50, "stock": 50, "base": 1},
            }
        )
        parts = self.build._split_test_tags(["/base", "/sale", "/account", "/stock"], 2)
        # Every part is a range of the sorted tags, so the cut lands where the
        # weight of the range reaches the target. sale and stock stay together
        # because they are next to each other, even if that is not the most
        # even split.
        self.assertEqual(parts, [["/account", "/base"], ["/sale", "/stock"]])

    def test_a_tag_heavier_than_the_target_gets_a_part_of_its_own(self):
        self.env["runbot.build.stat"].create(
            {
                "build_id": self.build.id,
                "category": "test_time",
                "values": {"sale": 300, "account": 1, "base": 1, "stock": 1},
            }
        )
        parts = self.build._split_test_tags(["/base", "/sale", "/account", "/stock"], 3)
        self.assertEqual(parts, [["/account", "/base"], ["/sale"], ["/stock"]])

    def test_the_heaviest_part_is_as_light_as_ranges_allow(self):
        self.env["runbot.build.stat"].create(
            {
                "build_id": self.build.id,
                "category": "test_time",
                "values": {"mod_a": 126, "mod_b": 106, "mod_c": 95, "mod_d": 63, "mod_e": 42, "mod_f": 40, "mod_g": 37},
            }
        )
        parts = self.build._split_test_tags(["/mod_a", "/mod_b", "/mod_c", "/mod_d", "/mod_e", "/mod_f", "/mod_g"], 4)
        # Cutting at the average would give the last part mod_d to mod_g, 182
        # seconds against the 158 of this one.
        self.assertEqual(
            parts,
            [["/mod_a"], ["/mod_b"], ["/mod_c", "/mod_d"], ["/mod_e", "/mod_f", "/mod_g"]],
        )

    def test_tags_without_recorded_time_are_still_spread(self):
        parts = self.build._split_test_tags(["/sale", "/account", "/stock", "/base"], 2)
        self.assertEqual(sum(len(part) for part in parts), 4)
        self.assertEqual([len(part) for part in parts], [2, 2])

    def test_no_empty_child_when_there_are_more_parts_than_tags(self):
        self.assertEqual(self.build._split_test_tags(["/sale"], 4), [["/sale"]])

    def test_children_ask_for_no_at_install_test(self):
        with self._patch_available():
            self.build._create_post_install_children(1)

        # A build with nothing to update runs the at_install tests of every
        # module, and the parent already ran them.
        self.assertIn("-at_install", self._tags_of(self.build.children_ids))

    def test_children_inherit_the_config_data_of_the_parent(self):
        # skip_requirements is the one that hurts: without it the child pip
        # installs the requirements of every repo, and it has no network.
        self.params.config_data = {"skip_requirements": True}
        with self._patch_available():
            self.build._create_post_install_children(1)

        self.assertTrue(self.build.children_ids.params_id.config_data["skip_requirements"])

    def test_children_restore_the_database_of_the_parent(self):
        with self._patch_available():
            self.build._create_post_install_children(1)

        child = self.build.children_ids
        dump_url = child.params_id.config_data["dump_url"]
        self.assertTrue(
            dump_url.endswith("%s-all.zip" % self.build.dest),
            "the children restore the dump of the parent, not one of their own",
        )
        self.assertNotIn(child.dest, dump_url)
        self.assertEqual(child.params_id.config_id, self.env.ref("runbot_ux.build_config_test_post_install"))
