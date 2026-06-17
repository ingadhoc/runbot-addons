import http.client
import logging
import os
import socket
import subprocess
import time

from odoo import _, api, fields, models
from odoo.addons.runbot.container import sanitize_container_name
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DOCKER_TIMEOUT = 20
# Symlink each oba-XX dir carries, pointing at its build's read-only sources.
OBA_REPOSITORIES_LINK = "repositories"
# Seconds to wait for OpenCode to answer HTTP after docker run.
READY_TIMEOUT = 30.0
# ICP -> environment variable for each AI provider key. Only keys with a
# non-empty ICP are passed into the container.
API_KEY_ENV = {
    "runbot_opencode.anthropic_api_key": "ANTHROPIC_API_KEY",
    "runbot_opencode.openai_api_key": "OPENAI_API_KEY",
}


class RunbotOpencodeWorkspace(models.Model):
    """One OpenCode container per user: a personal, always-latest workspace.

    There is a single workspace per user (not tied to any build). It mounts the
    configured bundles' latest builds read-only so the user can read or ask
    questions about the code, plus a writable area for their own notes that
    survives between sessions.
    """

    _name = "runbot.opencode.workspace"
    _description = "Runbot OpenCode per-user workspace"
    _inherit = ["mail.thread"]

    user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        ondelete="cascade",
    )
    user_key = fields.Char(compute="_compute_user_key", store=True)
    container_name = fields.Char(compute="_compute_container_name", store=True)
    port = fields.Integer()
    state = fields.Selection(
        [
            ("idle", "Idle"),
            ("creating", "Creating"),
            ("running", "Running"),
            ("error", "Error"),
        ],
        default="idle",
        required=True,
    )
    last_activity = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        (
            "user_uniq",
            "unique(user_id)",
            "A user can only have one OpenCode workspace.",
        ),
    ]

    @api.depends("user_id")
    def _compute_user_key(self):
        signer = self.env["runbot.token.signer"]
        for workspace in self:
            workspace.user_key = signer._user_key(workspace.user_id) if workspace.user_id else False

    @api.depends("user_key")
    def _compute_container_name(self):
        for workspace in self:
            workspace.container_name = (
                sanitize_container_name(f"opencode_{workspace.user_key}") if workspace.user_key else False
            )

    # --- host path helpers -------------------------------------------------

    def _get_host_auth_dir_path(self):
        """Host folder with this user's state, shared with the VS Code attach
        (same root, same per-user layout)."""
        self.ensure_one()
        root = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "runbot_attach_vscode.auth_root",
                default=os.path.expanduser("~/.adhoc-runbot-auth"),
            )
        )
        return os.path.join(root, self.user_key)

    def _get_host_workspace_dir_path(self):
        """Host folder mounted into the container as /workspace."""
        self.ensure_one()
        return os.path.join(self._get_host_auth_dir_path(), "opencode-workspace")

    # --- port pool ---------------------------------------------------------

    @api.model
    def _find_free_port(self):
        """Return a free host port on loopback, picked by the OS (bind to 0)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    # --- latest build sources ---------------------------------------------

    def _get_host_builds_root_path(self):
        """Host folder with every build's data (runbot's static). Mounted
        read-only as .odoodata so the oba-XX `repositories` symlinks resolve to
        a build's sources inside the container, and the code stays read-only."""
        return self.env["runbot.runbot"]._path()

    def _get_host_oba_project_path(self):
        """Host path of the oba-project checkout."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("runbot_opencode.oba_project_path", default="/home/runbot/sync-repos/oba-project")
        )

    def _get_oba_project_memory_path(self):
        """Host path of the oba-project memory dir."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("runbot_opencode.oba_project_memory_path", default="/home/runbot/sync-repos/oba-project-memory")
        )

    def _get_bundles_env(self):
        """Build the OPENCODE_BUNDLES value: "dir_name:build_id,..." for each
        configured bundle, skipping those without a latest build."""
        entries = []
        for bundle in self.env["runbot.opencode.bundle"].search([]):
            build = bundle._latest_build()
            if build:
                entries.append(f"{bundle.dir_name}:{build.id}")
        return ",".join(entries)

    def _get_public_url(self):
        """Public address nginx serves this workspace at; matches the redirect
        target the controller sends the browser to (opencode-<user_key>.<host>)."""
        self.ensure_one()
        scheme = self.env["ir.config_parameter"].sudo().get_param("runbot_opencode.scheme", default="https")
        host = self.env["runbot.host"]._get_current_name()
        return f"{scheme}://opencode-{self.user_key}.{host}"

    # --- workspace files ---------------------------------------------------

    def _ensure_files(self):
        """Create the host folders the container mounts."""
        self.ensure_one()
        # Writable area for the user's own files.
        os.makedirs(os.path.join(self._get_host_workspace_dir_path(), "personal"), exist_ok=True)
        # Create the mounted subdirs as the runbot user, so they aren't created
        # as root by Docker on mount.
        auth_dir = self._get_host_auth_dir_path()
        for sub in (".cache", ".config", ".local", ".adhoc"):
            os.makedirs(os.path.join(auth_dir, sub), exist_ok=True)

    # --- container lifecycle ----------------------------------------------

    def _docker_container_running(self):
        self.ensure_one()
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
                capture_output=True,
                timeout=DOCKER_TIMEOUT,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return result.returncode == 0 and result.stdout.strip() == b"true"

    @api.model
    def _ensure_workspace(self, user):
        """Find or create the user's workspace and make sure it is running.
        Returns the workspace record."""
        workspace = self.search([("user_id", "=", user.id)], limit=1)
        if not workspace:
            workspace = self.create({"user_id": user.id})
        workspace._ensure_container()
        return workspace

    def _ensure_container(self):
        """Start the user's container if it isn't already running, refreshing
        the sources first. Calling it again while it is up only refreshes the
        sources and the last-activity stamp."""
        self.ensure_one()
        self._ensure_files()
        if self._docker_container_running():
            self.write({"state": "running", "last_activity": fields.Datetime.now()})
            return

        self.state = "creating"
        image = self.env["ir.config_parameter"].sudo().get_param("runbot_opencode.image")
        if not image:
            self.state = "error"
            raise UserError(_("Set the OpenCode image in runbot_opencode.image first."))
        if not self.port:
            self.port = self._find_free_port()

        host_workspace_dir_path = self._get_host_workspace_dir_path()
        host_builds_root_path = self._get_host_builds_root_path()
        host_oba_project_path = self._get_host_oba_project_path()
        host_oba_project_memory_path = self._get_oba_project_memory_path()
        host_auth_dir_path = self._get_host_auth_dir_path()
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "-p",
            f"127.0.0.1:{self.port}:4096",
            # Mount the per-user home subdirs OpenCode and adhoc-way write to
            # (.cache, .config, .local, .adhoc) so the user's identity, config
            # and logins persist between sessions, without exposing the rest of
            # the image's HOME.
            "-v",
            f"{host_auth_dir_path}/.cache:/home/odoo/.cache:rw",
            "-v",
            f"{host_auth_dir_path}/.config:/home/odoo/.config:rw",
            "-v",
            f"{host_auth_dir_path}/.local:/home/odoo/.local:rw",
            "-v",
            f"{host_auth_dir_path}/.adhoc:/home/odoo/.adhoc:rw",
            # Mount the user's workspace folder as /workspace so they can read and write their own files, and so OpenCode can store its own state there.
            "-v",
            f"{host_workspace_dir_path}:/home/odoo/workspace:rw",
            # Mount the whole builds root as .odoodata so the oba-XX symlinks resolve
            "-v",
            f"{host_builds_root_path}:/home/odoo/ctx/.odoodata:ro",
            # Shared, read-only oba-project (AGENTS.md, memory, conventions);
            # each bundle dir symlinks its entries in (see _ensure_oba_sources).
            "-v",
            f"{host_oba_project_path}:/home/odoo/ctx/.oba-project:ro",
            # Mount the oba-project memory dir read-only.
            "-v",
            f"{host_oba_project_memory_path}:/home/odoo/ctx/.oba-project-memory:ro",
        ]
        # Pass each configured AI key as an environment variable; skip the ones
        # left empty so we never inject a blank key.
        get_param = self.env["ir.config_parameter"].sudo().get_param
        for icp, env_var in API_KEY_ENV.items():
            value = get_param(icp)
            if value:
                cmd += ["-e", f"{env_var}={value}"]

        # Tell the container which build's sources sit under each bundle dir.
        bundles_env = self._get_bundles_env()
        if bundles_env:
            cmd += ["-e", f"OPENCODE_BUNDLES={bundles_env}"]

        # Let the container know its own public address.
        cmd += ["-e", f"OPENCODE_PUBLIC_URL={self._get_public_url()}"]

        # The image's ENTRYPOINT runs adhoc-way init and boots `opencode serve`,
        # so we run it with no command.
        cmd += [image]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=DOCKER_TIMEOUT, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self.state = "error"
            _logger.exception("docker run failed for workspace %s", self.id)
            raise UserError(_("Could not start the OpenCode container."))
        if result.returncode != 0:
            self.state = "error"
            _logger.error(
                "docker run for opencode workspace %s failed (rc=%s): %s",
                self.id,
                result.returncode,
                result.stderr.decode("utf-8", errors="replace"),
            )
            raise UserError(_("Could not start the OpenCode container."))
        self._wait_until_ready()
        self.write({"state": "running", "last_activity": fields.Datetime.now()})
        self._log_audit("opened")

    def _wait_until_ready(self):
        """Wait until OpenCode answers HTTP. docker opens the port as soon as
        the container starts, but OpenCode needs a moment more to serve; without
        this wait the user's first request would hit an error page."""
        self.ensure_one()
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=0.5)
                try:
                    conn.request("GET", "/")
                    resp = conn.getresponse()
                    resp.read()
                finally:
                    conn.close()
                if resp.status < 500:
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.3)
        self.state = "error"
        _logger.error("OpenCode on port %s not ready in %ss", self.port, READY_TIMEOUT)
        raise UserError(_("OpenCode did not start in time; try again."))

    def _stop_container(self):
        for workspace in self:
            if workspace.container_name:
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", workspace.container_name],
                        capture_output=True,
                        timeout=DOCKER_TIMEOUT,
                        check=False,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    _logger.warning("docker rm failed for %s", workspace.container_name)
            # The workspace folder is left on the host, so the user keeps their
            # files between sessions.
            if workspace.state == "running":
                workspace._log_audit("closed")
            workspace.write({"state": "idle", "port": False})

    def action_stop_container(self):
        """Stop button on the admin form (buttons can't call private methods)."""
        self._stop_container()

    def touch(self):
        """Mark the workspace as recently used (called by the auth check).

        Write at most once a minute: OpenCode makes many requests and the
        cleanup job only looks every few hours, so writing on each one is wasted."""
        threshold = fields.Datetime.subtract(fields.Datetime.now(), seconds=60)
        to_refresh = self.filtered(lambda w: not w.last_activity or w.last_activity < threshold)
        if to_refresh:
            to_refresh.sudo().write({"last_activity": fields.Datetime.now()})

    def _log_audit(self, event):
        """Post an internal note recording who opened/closed the workspace."""
        self.ensure_one()
        self.message_post(
            body=_("OpenCode workspace %s by %s", event, self.user_id.name),
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _cron_close_unused_workspaces(self):
        """Stop workspaces nobody has used for a while (ICP idle_timeout_hours,
        default 8h). The container is removed; the workspace record and the
        user's files stay."""
        hours = int(self.env["ir.config_parameter"].sudo().get_param("runbot_opencode.idle_timeout_hours", default="8"))
        deadline = fields.Datetime.subtract(fields.Datetime.now(), hours=hours)
        unused = self.search([("state", "=", "running"), ("last_activity", "<", deadline)])
        unused._stop_container()
