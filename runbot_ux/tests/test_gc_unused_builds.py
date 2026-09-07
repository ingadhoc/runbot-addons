from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestGcUnusedBuilds(RunbotCase):
    """Tests for RunbotBuild._cron_gc_unused_builds"""

    def setUp(self):
        super().setUp()
        # The cron subtracts these, so the delay it writes is a known number.
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("runbot.db_gc_days", 7)
        icp.set_param("runbot.db_gc_days_child", 3)

    def _batch(self, bundle):
        """A new batch on the bundle, which becomes the one the bundle uses."""
        batch = self.Batch.create({"bundle_id": bundle.id})
        bundle.last_batch = batch
        return batch

    def _build(self, batch, link_type="created", **values):
        params = self.base_params.copy({"create_batch_id": batch.id})
        build = self.Build.create({"params_id": params.id, "local_state": "done", **values})
        self.env["runbot.batch.slot"].create(
            {
                "batch_id": batch.id,
                "build_id": build.id,
                "params_id": params.id,
                "trigger_id": self.trigger_server.id,
                "link_type": link_type,
            }
        )
        return build

    def test_build_of_an_older_batch_is_freed(self):
        old = self._build(self._batch(self.dev_bundle))
        current = self._build(self._batch(self.dev_bundle))
        self.Build._cron_gc_unused_builds()
        self.assertEqual(old.gc_delay, -8, "the bundle has run again, so nobody needs this build")
        self.assertEqual(current.gc_delay, 0, "the build the bundle still uses is kept")

    def test_build_used_by_the_last_batch_is_kept(self):
        build = self._build(self._batch(self.dev_bundle))
        # The newest batch uses this build instead of making one of its own.
        last = self._batch(self.dev_bundle)
        self.env["runbot.batch.slot"].create(
            {
                "batch_id": last.id,
                "build_id": build.id,
                "params_id": build.params_id.id,
                "trigger_id": self.trigger_server.id,
                "link_type": "matched",
            }
        )
        self.Build._cron_gc_unused_builds()
        self.assertEqual(build.gc_delay, 0, "the newest batch still uses this build")

    def test_child_keeps_its_own_days(self):
        parent = self._build(self._batch(self.dev_bundle))
        child = self.Build.create(
            {
                "params_id": self.base_params.copy({"create_batch_id": parent.create_batch_id.id}).id,
                "parent_id": parent.id,
                "local_state": "done",
            }
        )
        self._batch(self.dev_bundle)
        self.Build._cron_gc_unused_builds()
        self.assertEqual(parent.gc_delay, -8)
        self.assertEqual(child.gc_delay, -4, "a child is kept for db_gc_days_child, not for the days of its parent")

    def test_parent_waiting_for_a_child_is_kept(self):
        parent = self._build(self._batch(self.dev_bundle))
        child = self.Build.create(
            {
                "params_id": self.base_params.copy({"create_batch_id": parent.create_batch_id.id}).id,
                "parent_id": parent.id,
                "local_state": "testing",
            }
        )
        self._batch(self.dev_bundle)
        self.Build._cron_gc_unused_builds()
        self.assertEqual(parent.gc_delay, 0, "the child still has to restore the dump of its parent")
        self.assertEqual(child.gc_delay, 0)

    def test_sticky_bundle_is_kept(self):
        old = self._build(self._batch(self.master_bundle))
        self._batch(self.master_bundle)
        self.Build._cron_gc_unused_builds()
        self.assertTrue(self.master_bundle.sticky, "master is a base bundle, so it is sticky")
        self.assertEqual(old.gc_delay, 0, "on a sticky bundle the build before is still useful")

    def test_bundle_without_a_live_branch_is_freed(self):
        build = self._build(self._batch(self.dev_bundle))
        # The bundle has two branches in the fixture: the branch and the PR.
        self.dev_bundle.branch_ids.alive = False
        self.Build._cron_gc_unused_builds()
        self.assertEqual(build.gc_delay, -8, "the PR is closed, so even the last build is freed")
