import logging
import socket
import subprocess
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

VSCODE_CONTAINER_PORT = 8071
VSCODE_READY_TIMEOUT = 5.0


class RunbotBuild(models.Model):
    _inherit = "runbot.build"

    vscode_url = fields.Char(compute="_compute_vscode_url", store=True)

    def _has_vscode_layer(self):
        """True if the build's Dockerfile attaches our code-server reference layer."""
        self.ensure_one()
        source_layer = self.env.ref("runbot_attach_vscode.docker_layer_code_server", raise_if_not_found=False)
        if not source_layer:
            return False
        return any(
            layer.layer_type == "reference_layer" and layer.reference_docker_layer_id == source_layer
            for layer in self.params_id.dockerfile_id.layer_ids
        )

    @api.depends("global_state", "params_id.dockerfile_id")
    def _compute_vscode_url(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        suffix = get_param("runbot_attach_vscode.url_suffix", default="vscode")
        scheme = get_param("runbot_attach_vscode.scheme", default="https")
        for build in self:
            if build.global_state in ("done", "running") and build.dest and build.host and build._has_vscode_layer():
                build.vscode_url = f"{scheme}://{build.dest}-{suffix}.{build.host}"
            else:
                build.vscode_url = False

    def action_open_vscode(self):
        """Backend button entry-point. We funnel through the HTTP controller
        (rather than redirecting straight to vscode_url) because the
        controller has to set the auth cookie on the parent domain — model
        methods returning `ir.actions.act_url` can't attach cookies."""
        self.ensure_one()
        if not self.env.user._is_internal():
            raise UserError(_("Only internal users can open a VS Code session."))
        if not self.vscode_url:
            raise UserError(
                _("Build has no destination/host yet — wake it first."),
            )
        return {
            "type": "ir.actions.act_url",
            "url": f"/runbot/vscode/{self.id}",
            "target": "new",
        }

    def _ensure_code_server_running(self, container_name):
        """Start code-server inside the running build container.

        Repeated calls are safe: if code-server is already up, a second
        attempt fails with EADDRINUSE and exits without affecting the
        running instance.
        """
        inner_cmd = (
            f"code-server --bind-addr 0.0.0.0:{VSCODE_CONTAINER_PORT} "
            "--auth none /data/build "
            ">/tmp/code-server.log 2>&1"
        )
        try:
            result = subprocess.run(
                ["docker", "exec", "-d", container_name, "sh", "-c", inner_cmd],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            _logger.exception("docker exec failed for %s", container_name)
            raise UserError(_("Could not start code-server in the build container."))
        if result.returncode != 0:
            _logger.error(
                "docker exec to start code-server failed (rc=%s): %s",
                result.returncode,
                result.stderr.decode("utf-8", errors="replace"),
            )
            raise UserError(_("Could not start code-server in the build container."))
        deadline = time.monotonic() + VSCODE_READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port + 2), timeout=0.3):
                    return
            except OSError:
                time.sleep(0.3)
        _logger.warning(
            "code-server did not start listening on port %s within %ss for build %s",
            self.port + 2,
            VSCODE_READY_TIMEOUT,
            self.id,
        )
