import ipaddress

from odoo.addons.runbot.controllers.frontend import route
from odoo.exceptions import ValidationError
from odoo.http import Controller, request


class RunbotTrustedIp(Controller):
    @route(
        ["/runbot/trusted_ip"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
        methods=["GET", "POST"],
    )
    def trusted_ip(self, ip=None, **kwargs):
        """Let an internal user trust their IP for today, so they can write code on live builds."""
        if not request.env.user._is_internal():
            return request.not_found()
        values = {"title": "Trust my IP", "ip": request.httprequest.remote_addr, "error": False, "saved": False}
        if not ipaddress.ip_address(values["ip"]).is_global:
            values["ip"] = ""
        if request.httprequest.method == "POST":
            values["ip"] = ip = (ip or "").strip()
            try:
                with request.env.cr.savepoint():
                    request.env["runbot.trusted.ip"].sudo().create({"ip": ip, "user_id": request.env.user.id})
            except ValidationError as exc:
                values["error"] = exc.args[0]
            else:
                values["saved"] = True
        return request.render("runbot_ux.trusted_ip_page", values)
