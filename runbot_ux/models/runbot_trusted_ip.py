import ipaddress

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RunbotTrustedIp(models.Model):
    _name = "runbot.trusted.ip"
    _description = "IP trusted for today to write code on live builds"

    ip = fields.Char(required=True)
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)

    @api.constrains("ip")
    def _check_ip(self):
        # A bad value here breaks the nginx config of every new build
        for rec in self:
            try:
                address = ipaddress.ip_address(rec.ip)
            except ValueError:
                raise ValidationError(_("%s is not a valid IP address.", rec.ip)) from None
            if not address.is_global:
                raise ValidationError(_("%s is not a public IP address.", rec.ip))

    @api.model
    def _get_trusted_ips(self):
        """IPs from the runbot_ux.trusted_ips parameter plus the ones added for today."""
        param = self.env["ir.config_parameter"].sudo().get_param("runbot_ux.trusted_ips", "")
        ips = {ip.strip() for ip in param.split(",")} | set(self.sudo().search([]).mapped("ip"))
        return sorted(ips - {""})

    @api.model
    def _cron_clear(self):
        self.search([]).unlink()
