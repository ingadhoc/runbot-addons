from odoo import models, fields


class TransifexProject(models.Model):
    _name = "transifex.project"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'slug'

    slug = fields.Char(required=True)
    organization_slug = fields.Char(required=True)
    branch_ids = fields.One2many('runbot.branch', 'transifex_project_id', domain=[('bundle_id.is_base', '=', True)])
    # mostrar en la tree: remote y name (o bundle)
    api_token = fields.Char(required=True)
    periodicity = fields.Char('Periodicity (days)')
    github_token = fields.Char()
