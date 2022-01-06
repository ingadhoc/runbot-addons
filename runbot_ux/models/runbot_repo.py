from odoo import models


class RunbotRepo(models.Model):
    _name = "runbot.repo"
    _inherit = ["runbot.repo", "mail.activity.mixin"]
