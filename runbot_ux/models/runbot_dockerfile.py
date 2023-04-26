from odoo import models, fields


class RunbotBuild(models.Model):
    _inherit = 'runbot.dockerfile'

    skip_requirements = fields.Boolean('Skip requirements.txt auto install')
