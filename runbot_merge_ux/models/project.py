##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

from odoo import fields, models


class Project(models.Model):
    _inherit = "runbot_merge.project"

    default_bump_policy = fields.Selection(
        [
            ("bump", "bump"),
            ("nobump", "nobump"),
        ],
        help="Default bump policy applied to PRs that have no explicit bump/nobump command. "
        "Set to 'nobump' to exclude this project from the bump/nobump requirement.",
    )
