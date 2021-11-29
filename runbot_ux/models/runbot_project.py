from odoo import models, fields


class RunbotProject(models.Model):
    _inherit = 'runbot.project'
    _order = 'sequence'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(required=True, default=10)
