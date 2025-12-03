from odoo import http
from odoo.http import request


class WeblateController(http.Controller):
    @http.route(
        "/weblate",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_projects_info(self, token=None, **kwargs):
        """Return repository information from all active Weblate projects for component generation.

        Requires a valid token from system parameter 'runbot_server.token'.

        Args:
            token: token for authentication

        Returns JSON with list of repositories containing:
        - owner: Repository owner/organization
        - repo_name: Repository name
        - branch_name: Branch name
        """
        # Validate token
        expected_token = request.env["ir.config_parameter"].sudo().get_param("runbot_server.token")
        if not expected_token or token != expected_token:
            return request.make_json_response({"status": "error", "message": "Invalid or missing token"}, status=401)

        projects = request.env["weblate.project"].sudo().search([("active", "=", True)])

        data = []
        for project in projects:
            for branch in project.branch_ids:
                if branch.remote_id:
                    data.append(
                        {
                            "owner": branch.remote_id.owner,
                            "repo": branch.remote_id.repo_name,
                            "branch": branch.name,
                        }
                    )

        return request.make_json_response({"status": "success", "data": data})
