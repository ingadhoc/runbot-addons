import logging
import socket
import time

import docker
from odoo import _, api, fields, models
from odoo.addons.runbot.container import docker_state
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
        self.ensure_one()
        if not self.env.user._is_internal():
            raise UserError(_("Only internal users can open a VS Code session."))
        if not self.vscode_url:
            raise UserError(
                _("Build has no destination/host yet — wake it first."),
            )
        container_name = self._get_docker_name()
        if docker_state(container_name, self._path()) != "RUNNING":
            raise UserError(
                _("Build container is not running. Wake it up before opening VS Code."),
            )
        self._ensure_code_server_running(container_name)
        return {
            "type": "ir.actions.act_url",
            "url": self.vscode_url,
            "target": "new",
        }

    def _ensure_code_server_running(self, container_name):
        """Idempotently start code-server inside the running build container.

        Uses `docker exec` with detach so the call returns immediately. The
        shell guard (`pgrep ... || exec code-server ...`) makes a second
        click a no-op if code-server is already up. After kicking off the
        exec, we briefly poll the host port until code-server starts
        accepting connections so the user's browser does not race against
        the bind.
        """
        try:
            container = docker.from_env().containers.get(container_name)
            container.exec_run(
                [
                    "sh",
                    "-c",
                    "pgrep -f code-server >/dev/null || "
                    f"exec code-server --bind-addr 0.0.0.0:{VSCODE_CONTAINER_PORT} "
                    "--auth none /data/build "
                    ">/tmp/code-server.log 2>&1",
                ],
                detach=True,
            )
        except docker.errors.NotFound:
            raise UserError(
                _("Build container '%s' not found.", container_name),
            )
        except Exception:
            _logger.exception("Failed to start code-server in %s", container_name)
            raise UserError(
                _("Could not start code-server in the build container. Check the runbot logs."),
            )
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
