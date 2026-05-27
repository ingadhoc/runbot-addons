import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class RunbotBuild(models.Model):
    _inherit = "runbot.build"

    # True when this build can open VS Code: its Dockerfile includes the
    # code-server layer and the build is up with an address. Drives the button;
    # the real per-user address comes from _vscode_session_url.
    vscode_available = fields.Boolean(compute="_compute_vscode_available", store=True)
    vscode_session_ids = fields.One2many(
        "runbot.build.vscode.session",
        "build_id",
        string="VS Code sessions",
    )

    def _has_vscode_layer(self):
        """True if this build's Dockerfile includes the code-server layer."""
        self.ensure_one()
        source_layer = self.env.ref("runbot_attach_vscode.docker_layer_code_server", raise_if_not_found=False)
        if not source_layer:
            return False
        return any(
            layer.layer_type == "reference_layer" and layer.reference_docker_layer_id == source_layer
            for layer in self.params_id.dockerfile_id.layer_ids
        )

    @api.depends("global_state", "params_id.dockerfile_id")
    def _compute_vscode_available(self):
        for build in self:
            build.vscode_available = bool(
                build.global_state in ("done", "running") and build.dest and build.host and build._has_vscode_layer()
            )

    def _vscode_session_url(self, session):
        """The user's personal VS Code address: <dest>-<suffix>-<user_key>.<host>.

        nginx sends each user's address to their own container
        (see views/runbot_nginx.xml).
        """
        self.ensure_one()
        get_param = self.env["ir.config_parameter"].sudo().get_param
        suffix = get_param("runbot_attach_vscode.url_suffix", default="vscode")
        scheme = get_param("runbot_attach_vscode.scheme", default="https")
        return f"{scheme}://{self.dest}-{suffix}-{session.user_key}.{self.host}"

    def _ensure_user_vscode_container(self, user):
        """Find or create this user's session on the build and make sure its
        container is running. Returns the session."""
        self.ensure_one()
        Session = self.env["runbot.build.vscode.session"].sudo()
        session = Session.search(
            [("build_id", "=", self.id), ("user_id", "=", user.id)],
            limit=1,
        )
        if not session:
            session = Session.create({"build_id": self.id, "user_id": user.id})
        session._ensure_container()
        return session

    def _kill(self, result=None):
        # Stop every user's VS Code container before the build's own container
        # goes away.
        self.vscode_session_ids.filtered(lambda s: s.state != "dead")._stop_container()
        return super()._kill(result=result)
