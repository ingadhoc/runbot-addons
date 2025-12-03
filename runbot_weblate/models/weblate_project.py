import logging
from urllib.parse import urlparse

from github import Auth, Github
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WeblateProject(models.Model):
    _name = "weblate.project"
    _description = "Weblate Project"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, help="Project name")
    weblate_url = fields.Char(
        string="Weblate URL",
        required=True,
        default="https://translation.dev-adhoc.com",
        help="Weblate base URL (e.g., https://hosted.weblate.org)",
    )
    version_id = fields.Many2one(
        "runbot.version",
        required=True,
        help="Odoo version for this Weblate project",
    )
    branch_ids = fields.One2many(
        "runbot.branch",
        "weblate_project_id",
        string="Branches",
        domain="[('bundle_id.is_base', '=', True), ('bundle_id.version_id', '=', version_id)]",
    )
    active = fields.Boolean(default=True)

    @api.constrains("weblate_url")
    def _check_weblate_url(self):
        """Validate that weblate_url is a valid HTTPS URL"""
        for record in self:
            if record.weblate_url:
                parsed = urlparse(record.weblate_url)
                if not all([parsed.scheme, parsed.netloc]) or parsed.scheme != "https":
                    raise ValidationError("Weblate URL must be a valid HTTPS URL (e.g., https://hosted.weblate.org)")

    def _get_github_client(self):
        """Get authenticated GitHub client"""
        github_token = self.env["ir.config_parameter"].sudo().get_param("github_transbot_token")
        if not github_token:
            raise UserError("GitHub token 'github_transbot_token' is not configured in system parameters")
        return Github(auth=Auth.Token(github_token))

    def _create_github_webhook(self, owner, repo_name):
        """Create webhook in GitHub repository to notify Weblate.
        Checks if webhook already exists before creating to avoid duplicates.

        Args:
            owner: Repository owner
            repo_name: Repository name

        Returns:
            Hook object (existing or newly created)
        """
        self.ensure_one()
        webhook_url = f"{self.weblate_url.rstrip('/')}/hooks/github/"

        try:
            gh = self._get_github_client()
            gh_repo = gh.get_repo(f"{owner}/{repo_name}")

            # Check if webhook already exists
            hooks = gh_repo.get_hooks()
            for hook in hooks:
                if hook.config.get("url") == webhook_url:
                    _logger.info(
                        "GitHub webhook already exists for %s/%s pointing to %s", owner, repo_name, webhook_url
                    )
                    return hook

            # Create webhook if it doesn't exist
            hook = gh_repo.create_hook(
                name="web",
                config={
                    "url": webhook_url,
                    "content_type": "form",
                    "insecure_ssl": "0",
                },
                events=["push"],
                active=True,
            )

            _logger.info("Created GitHub webhook for %s/%s pointing to %s", owner, repo_name, webhook_url)
            return hook
        except Exception as e:
            raise UserError(f"Failed to create GitHub webhook: {str(e)}")

    def action_create_webhooks(self):
        """Create GitHub webhooks for all repositories in branches"""
        self.ensure_one()
        if not self.branch_ids:
            raise UserError("No branches configured for this Weblate project")

        # Get unique repositories from branches
        repositories = {}
        for branch in self.branch_ids:
            owner = branch.remote_id.owner
            repo_name = branch.remote_id.repo_name
            if owner and repo_name:
                repo_key = f"{owner}/{repo_name}"
                if repo_key not in repositories:
                    repositories[repo_key] = (owner, repo_name)

        if not repositories:
            raise UserError("No valid repositories found in branches")

        for repo_key, (owner, repo_name) in repositories.items():
            self._create_github_webhook(owner, repo_name)

    def action_view_branches(self):
        """Open tree view of related branches"""
        self.ensure_one()
        return {
            "name": "Branches",
            "type": "ir.actions.act_window",
            "res_model": "runbot.branch",
            "view_mode": "tree,form",
            "domain": [("weblate_project_id", "=", self.id)],
        }

    def action_open_weblate(self):
        """Open Weblate URL in browser"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self.weblate_url,
            "target": "new",
        }
