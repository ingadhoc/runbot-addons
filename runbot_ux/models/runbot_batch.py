from odoo import models


class RunbotBatch(models.Model):
    _inherit = "runbot.batch"

    def _start_builds(self):
        draft_branches = self.bundle_id.branch_ids.filtered(lambda b: b.alive and b.draft)
        if draft_branches:
            self._log("Draft pr, not starting builds: %s", ",".join(draft_branches.mapped("name")))
            return
        return super()._start_builds()
