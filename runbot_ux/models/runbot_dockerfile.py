from odoo import fields, models


class RunbotBuild(models.Model):
    _inherit = "runbot.dockerfile"

    skip_requirements = fields.Boolean("Skip requirements.txt auto install")
