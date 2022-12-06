from odoo import models, api

class BuildParameters(models.Model):

    _inherit = 'runbot.build.params'

    @api.depends('trigger_id')
    def _set_skip_requirements(self):
        for rec in self:
            rec.skip_requirements = rec.trigger_id.skip_requirements
