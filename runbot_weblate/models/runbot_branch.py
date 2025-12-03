from odoo import api, fields, models


class RunbotBranch(models.Model):
    _inherit = "runbot.branch"

    weblate_project_id = fields.Many2one("weblate.project", string="Weblate Project")
    weblate_project_url = fields.Char(
        string="Weblate Project URL",
        compute="_compute_weblate_project_url",
        help="URL to the Weblate project for this branch",
    )

    @api.depends("weblate_project_id.weblate_url", "remote_id.repo_name", "bundle_id.version_id.number")
    def _compute_weblate_project_url(self):
        """Compute Weblate project URL based on repo name and version.
        Format: {weblate_url}/projects/{repo-name}-{version}-0/
        """
        for branch in self:
            if branch.weblate_project_id and branch.remote_id and branch.bundle_id.version_id:
                base_url = branch.weblate_project_id.weblate_url.rstrip("/")
                repo_name = branch.remote_id.repo_name
                version = branch.bundle_id.version_id.name.replace(".", "-")
                branch.weblate_project_url = f"{base_url}/projects/{repo_name}-{version}/"
            else:
                branch.weblate_project_url = False
