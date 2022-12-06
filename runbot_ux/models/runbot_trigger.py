from odoo import models, fields


class RunbotTrigger(models.Model):
    _name = 'runbot.trigger'
    _inherit = ['runbot.trigger', 'mail.activity.mixin']

    project_id = fields.Many2one(tracking=True)
    config_id = fields.Many2one(tracking=True)
    repo_ids = fields.Many2many(tracking=True) 
    dependency_ids = fields.Many2many(tracking=True) 
    version_domain = fields.Char(tracking=True)
    skip_requirements = fields.Boolean('Skip requirements.txt auto install')
