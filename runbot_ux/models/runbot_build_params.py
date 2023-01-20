from odoo import fields, models, api


class BuildParameters(models.Model):

    _inherit = 'runbot.build.params'

    skip_requirements = fields.Boolean('Skip requirements.txt auto install', compute="_compute_skip_requirements")

    @api.depends('dockerfile_id', 'dockerfile_id.skip_requirements')
    def _compute_skip_requirements(self):
        for rec in self:
            rec.skip_requirements = rec.dockerfile_id.skip_requirements
