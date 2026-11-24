import ipaddress

from odoo.http import Controller, request, route


def _is_public_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


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
        if not _is_public_ip(values["ip"]):
            values["ip"] = ""
        if request.httprequest.method == "POST":
            values["ip"] = ip = (ip or "").strip()
            # A bad value here breaks the nginx config of every new build
            if not _is_public_ip(ip):
                values["error"] = f"{ip} is not a public IP address."
            else:
                params = request.env["ir.config_parameter"].sudo()
                ips = params.get_param("runbot_ux.trusted_ips_today", "").split(",")
                if ip not in ips:
                    params.set_param("runbot_ux.trusted_ips_today", ",".join(filter(None, ips + [ip])))
                request.env["ir.logging"].sudo().create(
                    {
                        "name": __name__,
                        "type": "server",
                        "level": "INFO",
                        "dbname": request.env.cr.dbname,
                        "message": f"{request.env.user.login} trusted IP {ip} for today",
                        "path": __file__,
                        "func": "trusted_ip",
                        "line": "0",
                    }
                )
                values["saved"] = True
        return request.render("runbot_ux.trusted_ip_page", values)


class RunbotBuildApi(Controller):
    @route(["/runbot/api/build/<int:build_id>"], type="http", auth="public", methods=["GET"], sitemap=False)
    def build_api(self, build_id, **kwargs):
        """Public build summary: only the fields listed here are exposed."""
        build = request.env["runbot.build"].sudo().browse(build_id).exists()
        if not build:
            return request.not_found()
        data = self._build_summary(build)
        data["parent_id"] = build.parent_id.id or None
        data["children"] = [self._build_summary(child) for child in build.children_ids.sorted("id")]
        return request.make_json_response(data)

    def _build_summary(self, build):
        logs = []
        if build.host_id and build.log_list:
            base = build._http_log_url()
            logs = [f"{base}{name}.txt" for name in build.log_list.split(",")]
        return {
            "id": build.id,
            "description": build.description or "",
            "state": build.global_state,
            "result": build.global_result,
            "logs": logs,
        }
