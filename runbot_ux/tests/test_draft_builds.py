from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestDraftBuilds(RunbotCase):
    """Tests for RunbotBatch._start_builds on a bundle with a draft pr"""

    def _slot(self):
        """An empty slot on the bundle's batch, the way _prepare leaves it."""
        return self.env["runbot.batch.slot"].create(
            {
                "batch_id": self.dev_batch.id,
                "params_id": self.base_params.id,
                "trigger_id": self.trigger_server.id,
                "link_type": "created",
            }
        )

    def test_draft_pr_starts_no_build(self):
        self.dev_pr.draft = True
        slot = self._slot()
        self.dev_batch._start_builds()
        self.assertFalse(slot.build_id, "the pr is draft, nothing should build")

    def test_pr_out_of_draft_starts_the_build(self):
        self.dev_pr.draft = False
        slot = self._slot()
        self.dev_batch._start_builds()
        self.assertTrue(slot.build_id, "the pr is not draft, it builds as usual")
