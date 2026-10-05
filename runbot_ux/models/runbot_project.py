from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RunbotProject(models.Model):
    _inherit = "runbot.project"

    protect_live_builds = fields.Boolean(
        default=True,
        help="Live builds load runbot_build_guard and hide the database manager, "
        "so a visitor cannot run code on the server.",
    )

    @api.constrains("protect_live_builds", "group_ids")
    def _check_protect_live_builds(self):
        # A project without required groups is visible to every runbot user.
        if any(not project.protect_live_builds and not project.group_ids for project in self):
            raise ValidationError(_("Live builds of a public project must be protected."))
