from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RunbotBuild(models.Model):
    _inherit = "runbot.build"

    vscode_url = fields.Char(compute="_compute_vscode_url")

    @api.depends("dest", "host")
    def _compute_vscode_url(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        suffix = get_param("runbot_attach_vscode.url_suffix", default="vscode")
        scheme = get_param("runbot_attach_vscode.scheme", default="https")
        for build in self:
            if build.dest and build.host:
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
