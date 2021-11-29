from odoo import models, fields


class RunbotVersion(models.Model):
    _inherit = 'runbot.version'

    custom_pre_commands = fields.Char(
        help="Lista de lista de comandos a sumarse al final del pre-command. Por ej:\n"
        "[['sudo', 'pip3', 'install', '--upgrade', 'urlib2==xxx']]")
