from odoo import models


class RunbotBranch(models.Model):
    _inherit = "runbot.branch"

    def _recompute_infos(self, payload=None):
        was_draft = self.draft
        res = super()._recompute_infos(payload)
        batch = self.bundle_id.last_batch
        # Leaving draft builds the bundle again as if its heads were just pushed.
        if was_draft and not self.draft and batch.state == "preparing":
            for branch in self.bundle_id.branch_ids.filtered(lambda b: b.alive and b.head):
                batch._new_commit(branch)
        return res
