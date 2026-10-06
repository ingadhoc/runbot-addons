from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestStartCategory(RunbotCase):
    """Tests for RunbotTrigger._cron_start_category"""

    def test_only_base_bundles_with_a_matching_trigger(self):
        nightly = self.env.ref("runbot.nightly_category")
        self.master_bundle.is_base = True
        self.trigger_server.category_id = nightly

        self.trigger_server.version_domain = "[('name', '=', '17.0')]"
        self.Trigger._cron_start_category("runbot.nightly_category")
        batches = self.Batch.search([("category_id", "=", nightly.id)])
        self.assertFalse(batches, "the trigger does not apply to the bundle version")

        self.trigger_server.version_domain = False
        self.Trigger._cron_start_category("runbot.nightly_category")
        batches = self.Batch.search([("category_id", "=", nightly.id)])
        self.assertEqual(batches.bundle_id, self.master_bundle, "only the base bundle runs the nightly")

    def test_nightly_and_weekly_on_the_same_bundle(self):
        self.master_bundle.is_base = True
        self.trigger_server.category_id = self.env.ref("runbot.nightly_category")
        self.trigger_addons.category_id = self.env.ref("runbot.weekly_category")
        last_batch = self.master_bundle.last_batch
        # Both crons run at the same time.
        self.Trigger._cron_start_category("runbot.nightly_category")
        self.Trigger._cron_start_category("runbot.weekly_category")
        batches = self.Batch.search([("bundle_id", "=", self.master_bundle.id), ("state", "=", "preparing")])
        self.assertEqual(
            batches.category_id,
            self.env.ref("runbot.nightly_category") | self.env.ref("runbot.weekly_category"),
            "the weekly batch is not lost behind the nightly one",
        )
        self.assertEqual(self.master_bundle.last_batch, last_batch, "a push to the base branch gets its own batch")
