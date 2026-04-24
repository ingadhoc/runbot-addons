from odoo import fields, models


class RunbotRepo(models.Model):
    _inherit = "runbot.repo"

    test_modules = fields.Char(
        "Modules to test",
        tracking=True,
        help="Comma-separated list of module patterns used to dynamically select --test-tags "
        "when running tests. Supports fnmatch wildcards (e.g. 'sale,account_*') and "
        "exclusions prefixed with '-' (e.g. '-*,sale'). "
        "Leave empty to test all available modules (same convention as 'Modules to install'). "
        "To disable dynamic injection entirely, unset 'Test Enable' on the config step.",
    )
