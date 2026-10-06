from odoo import fields, models


class RunbotTrigger(models.Model):
    _inherit = "runbot.trigger"

    project_id = fields.Many2one(tracking=True)
    config_id = fields.Many2one(tracking=True)
    repo_ids = fields.Many2many(tracking=True)
    dependency_ids = fields.Many2many(tracking=True)
    version_domain = fields.Char(tracking=True)

    def _cron_start_category(self, category_xmlid):
        """Start a batch of the category on every base bundle that has a trigger for it."""
        category = self.env.ref(category_xmlid)
        triggers = self.search([("category_id", "=", category.id)])
        bundles = self.env["runbot.bundle"].search(
            [("is_base", "=", True), ("project_id", "in", triggers.project_id.ids)]
        )
        for bundle in bundles:
            if triggers.filtered(
                lambda t: t.project_id == bundle.project_id
                and (not t.version_domain or bundle.version_id.filtered_domain(t._get_version_domain()))
            ):
                # Not bundle._force(): it does nothing while the last batch is preparing,
                # and it would make this batch the one a push to the base branch joins.
                self.env["runbot.batch"].create(
                    {
                        "bundle_id": bundle.id,
                        "category_id": category.id,
                        "state": "preparing",
                        "last_update": fields.Datetime.now(),
                    }
                )
