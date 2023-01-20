from odoo import models, api

class BuildParameters(models.Model):

    _inherit = 'runbot.build.params'

    @api.depends('dockerfile_id', 'dockerfile_id.skip_requirements')
    def _set_skip_requirements(self):
        for rec in self:
            rec.skip_requirements = rec.dockerfile_id.skip_requirements
