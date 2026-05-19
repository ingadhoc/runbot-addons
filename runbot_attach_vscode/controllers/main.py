import logging

from odoo import _, http
from odoo.addons.runbot.container import docker_state
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class VsCodeController(http.Controller):
    @http.route(
        ["/runbot/vscode/<int:build_id>"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def open_vscode(self, build_id):
        """Lazy entry point for the frontend 'Open VS Code' dropdown.

        Starts code-server inside the build container (idempotent) and
        redirects the browser to the vscode_url. The frontend template
        cannot call the action_open_vscode model method directly because
        the dropdown is a plain <a> tag — it would navigate the browser
        to vscode_url straight away, bypassing the docker exec.
        """
        if not request.env.user._is_internal():
            return request.not_found()
        build = request.env["runbot.build"].browse(build_id).sudo()
        if not build.exists() or not build.vscode_url:
            return request.not_found()
        container_name = build._get_docker_name()
        if docker_state(container_name, build._path()) != "RUNNING":
            return request.render(
                "http_routing.http_error",
                {
                    "status_code": _("Build not running"),
                    "status_message": _("Wake the build up before opening VS Code."),
                },
            )
        try:
            build._ensure_code_server_running(container_name)
        except UserError as exc:
            return request.render(
                "http_routing.http_error",
                {"status_code": _("VS Code"), "status_message": exc.args[0]},
            )
        return request.redirect(build.vscode_url, code=302, local=False)
