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
    private = fields.Boolean(
        tracking=True,
        help="The repo is private on GitHub. The license-check step fails the build when a module "
        "of a public repo depends on Odoo Enterprise or on a module of a private repo.",
    )
    skip_private_dependency_check = fields.Boolean(
        tracking=True,
        help="Its modules may depend on Odoo Enterprise and on private repos even if the repo is "
        "public. Set it on agreed exceptions, or until the modules are fixed. The AGPL-3 rule "
        "of the license-check step still applies.",
    )
