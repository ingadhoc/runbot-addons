from odoo import fields, models


class RunbotTrigger(models.Model):
    _inherit = "runbot.trigger"

    project_id = fields.Many2one(tracking=True)
    config_id = fields.Many2one(tracking=True)
    repo_ids = fields.Many2many(tracking=True)
    dependency_ids = fields.Many2many(tracking=True)
    version_domain = fields.Char(tracking=True)
