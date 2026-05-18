from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
        return {
            "type": "ir.actions.act_url",
            "url": self.vscode_url,
            "target": "new",
        }
