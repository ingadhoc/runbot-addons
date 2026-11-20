from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    action_id = fields.Many2one(default=False)
