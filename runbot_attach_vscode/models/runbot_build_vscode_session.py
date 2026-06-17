import http.client
import json
import logging
import os
import socket
import subprocess
import time

from odoo import _, api, fields, models
from odoo.addons.runbot.container import sanitize_container_name
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Port code-server listens on inside each container. The matching port on the
# host is a free one the OS hands us per session (see _find_free_port).
VSCODE_CONTAINER_PORT = 8071
# How long a session may sit unused before we close it. Same length as the
# login token's lifetime, so the token and the container expire together.
SESSION_TTL_SECONDS = 4 * 3600
DOCKER_TIMEOUT = 20
# Home folder inside the container, where each user's login folders are mounted.
# Fixed by the build image, so it is a constant, not a setting.
CONTAINER_HOME = "/home/runbot"
# Seconds to wait for code-server to start serving HTTP after docker run.
READY_TIMEOUT = 30.0
# Path code-server answers 200 on once it is ready to serve.
READY_PROBE_PATH = "/healthz"
# MCP servers pre-seeded into ~/.claude.json so users only need to pick
# one in /mcp and authenticate.
PRESEED_MCP_SERVERS = {
    "tuqui-adhoc": {
        "type": "http",
        "url": "https://tuqui.com/mcp/adhoc",
    },
}
# Defaults seeded into code-server's settings.json on a user's first session.
VSCODE_USER_SETTINGS = {
    "workbench.colorTheme": "Default Dark Modern",
    "workbench.startupEditor": "none",
    "remote.autoForwardPorts": False,
    "security.workspace.trust.enabled": False,
    "security.workspace.trust.banner": "never",
    "security.workspace.trust.startupPrompt": "never",
    "security.workspace.trust.untrustedFiles": "open",
}
# Extensions installed before code-server starts. They land in the mounted
# ~/.local, so reinstalling on later sessions is a quick no-op.
VSCODE_EXTENSIONS = [
    "Anthropic.claude-code",
    "zaaack.markdown-editor",
]


class RunbotBuildVscodeSession(models.Model):
    """One code-server container per user, on a single build.

    Each user gets their own container, so several people can open the same
    build at the same time without seeing each other's logins. The container
    can read the build's source code and reach its database, but only the
    owner's saved logins (Claude, codex, gemini) are mounted into it.
    """

    _name = "runbot.build.vscode.session"
    _description = "Runbot VS Code per-user session"

    build_id = fields.Many2one(
        "runbot.build",
        required=True,
        index=True,
        ondelete="cascade",
    )
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
        [("starting", "Starting"), ("running", "Running"), ("dead", "Dead")],
        default="starting",
        required=True,
    )
    last_seen = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        (
            "build_user_uniq",
            "unique(build_id, user_id)",
            "A user can only have one VS Code session per build.",
        ),
    ]

    @api.depends("user_id")
    def _compute_user_key(self):
        signer = self.env["runbot.token.signer"]
        for session in self:
            session.user_key = signer._user_key(session.user_id) if session.user_id else False

    @api.depends("build_id.dest", "user_key")
    def _compute_container_name(self):
        for session in self:
            if session.build_id.dest and session.user_key:
                session.container_name = sanitize_container_name(
                    f"{session.build_id.dest}_vscode_{session.user_key}",
                )
            else:
                session.container_name = False

    # --- host path helpers -------------------------------------------------

    def _auth_dir(self):
        """Host folder with this user's saved logins (Claude, codex, gemini)."""
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

    # --- port pool ---------------------------------------------------------

    @api.model
    def _find_free_port(self):
        """Return a free host port on loopback, picked by the OS (bind to 0)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

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

    def _build_source_mounts(self):
        """Return the build container's read-only /data/build/ mounts so we can
        mirror them; that is where runbot exposes the repo sources. Raises
        UserError if the build container cannot be read."""
        self.ensure_one()
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{json .Mounts}}", self.build_id._get_docker_name()],
                capture_output=True,
                timeout=DOCKER_TIMEOUT,
                check=True,
            )
            mounts = json.loads(result.stdout or b"[]")
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as exc:
            _logger.warning("could not read source mounts for build %s: %s", self.build_id.dest, exc)
            raise UserError(_("Could not read the build's files; make sure it is running and try again."))
        return [
            (m["Source"], m["Destination"])
            for m in mounts
            if m.get("Mode") == "ro" and m.get("Destination", "").startswith("/data/build/")
        ]

    def _ensure_container(self):
        """Start this user's container if it isn't already running.

        Calling it again while the container is up does nothing. The container
        only runs code-server (not the build's own Odoo), so the code being
        reviewed never runs next to the user's logins.
        """
        self.ensure_one()
        build = self.build_id
        if self._docker_container_running():
            self.write({"state": "running", "last_seen": fields.Datetime.now()})
            return
        if not self.port:
            self.port = self._find_free_port()

        auth_dir = self._auth_dir()
        # We create these folders as the runbot user, so they end up owned by
        # the same user the container runs as.
        for sub in (".claude", ".codex", ".gemini", ".local", ".adhoc"):
            os.makedirs(os.path.join(auth_dir, sub), exist_ok=True)
        # Seed the settings once; later sessions keep what the user changed.
        settings_dir = os.path.join(auth_dir, ".local", "share", "code-server", "User")
        settings_json = os.path.join(settings_dir, "settings.json")
        if not os.path.exists(settings_json):
            os.makedirs(settings_dir, exist_ok=True)
            with open(settings_json, "w") as f:
                json.dump(VSCODE_USER_SETTINGS, f, indent=4)
        # Claude Code keeps the logged-in account in ~/.claude.json (next to the
        # .claude folder, not inside it). Pre-seed the MCP servers here so the
        # user only needs to pick one in /mcp and authenticate.
        claude_json = os.path.join(auth_dir, ".claude.json")
        try:
            with open(claude_json) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        servers = data.setdefault("mcpServers", {})
        for name, cfg in PRESEED_MCP_SERVERS.items():
            servers.setdefault(name, cfg)
        with open(claude_json, "w") as f:
            json.dump(data, f, indent=2)

        image_tag = build.params_id.dockerfile_id.image_tag
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "-p",
            f"127.0.0.1:{self.port}:{VSCODE_CONTAINER_PORT}",
            "-v",
            f"{build._path()}:/data/build:ro",
            "-v",
            "/var/run/postgresql:/var/run/postgresql:rw",
            "-v",
            f"{os.path.join(auth_dir, '.claude')}:{CONTAINER_HOME}/.claude:rw",
            "-v",
            f"{claude_json}:{CONTAINER_HOME}/.claude.json:rw",
            "-v",
            f"{os.path.join(auth_dir, '.codex')}:{CONTAINER_HOME}/.codex:rw",
            "-v",
            f"{os.path.join(auth_dir, '.gemini')}:{CONTAINER_HOME}/.gemini:rw",
            "-v",
            f"{os.path.join(auth_dir, '.local')}:{CONTAINER_HOME}/.local:rw",
            "-v",
            f"{os.path.join(auth_dir, '.adhoc')}:{CONTAINER_HOME}/.adhoc:rw",
        ]
        # Mirror the repo sources runbot mounts on the build's own container,
        # so the side container sees the same /data/build/<repo>/ layout.
        for src, dst in self._build_source_mounts():
            cmd += ["-v", f"{src}:{dst}:ro"]
        # Install the extensions, then hand the process over to code-server
        # (exec keeps it as PID 1 so --rm and docker stop still work).
        startup = "".join(f'code-server --install-extension "{ext}" || true\n' for ext in VSCODE_EXTENSIONS)
        startup += "adhoc-way init || true\n"
        startup += f"exec code-server --bind-addr 0.0.0.0:{VSCODE_CONTAINER_PORT} --auth none /data/build"
        cmd += [image_tag, "bash", "-c", startup]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=DOCKER_TIMEOUT,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            _logger.exception("docker run failed for session %s", self.id)
            raise UserError(_("Could not start the VS Code container."))
        if result.returncode != 0:
            _logger.error(
                "docker run for vscode session %s failed (rc=%s): %s",
                self.id,
                result.returncode,
                result.stderr.decode("utf-8", errors="replace"),
            )
            raise UserError(_("Could not start the VS Code container."))
        # Send a real HTTP request, not just check that the port is open:
        # docker opens the port the moment the container starts, but
        # code-server needs another moment to actually serve. Without this
        # wait, the user's first click would land on an error page.
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=0.5)
                try:
                    conn.request("GET", READY_PROBE_PATH)
                    resp = conn.getresponse()
                    resp.read()
                finally:
                    conn.close()
                if resp.status < 500:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.3)
        else:
            _logger.error(
                "code-server on port %s did not become ready within %ss for session %s",
                self.port,
                READY_TIMEOUT,
                self.id,
            )
            raise UserError(_("VS Code did not start in time; try again."))
        self.write({"state": "running", "last_seen": fields.Datetime.now()})
        build._log(
            "vscode",
            "VS Code session opened by **%s**" % self.user_id.name,
            log_type="markdown",
        )

    def _stop_container(self):
        for session in self:
            if not session.container_name:
                session.state = "dead"
                continue
            try:
                subprocess.run(
                    ["docker", "stop", session.container_name],
                    capture_output=True,
                    timeout=DOCKER_TIMEOUT,
                    check=False,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                _logger.warning("docker stop failed for %s", session.container_name)
            if session._docker_container_running():
                _logger.error(
                    "VS Code container %s did not stop; the cleanup job will try again later",
                    session.container_name,
                )
                continue
            if session.state != "dead":
                session.build_id._log(
                    "vscode",
                    "VS Code session closed for **%s**" % session.user_id.name,
                    log_type="markdown",
                )
            session.state = "dead"

    def touch(self):
        """Mark the session as recently used (called on each editor request).

        We write at most once a minute: code-server makes lots of requests and
        the cleanup job only looks every few hours, so writing on every request
        would be wasted work."""
        threshold = fields.Datetime.subtract(fields.Datetime.now(), seconds=60)
        to_refresh = self.filtered(lambda s: not s.last_seen or s.last_seen < threshold)
        if to_refresh:
            to_refresh.sudo().write({"last_seen": fields.Datetime.now()})

    @api.model
    def _cron_close_unused_sessions(self):
        """Close sessions nobody has used for a while.

        A session counts as unused once nobody has touched it for 4 hours
        (SESSION_TTL_SECONDS): we stop its container, then remove the rows we
        already closed so the table doesn't grow forever."""
        deadline = fields.Datetime.subtract(
            fields.Datetime.now(),
            seconds=SESSION_TTL_SECONDS,
        )
        unused = self.search([("state", "!=", "dead"), ("last_seen", "<", deadline)])
        unused._stop_container()
        self.search([("state", "=", "dead")]).unlink()
