import re

from odoo import http
from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestNginxConfig(RunbotCase):
    def _render(self, builds):
        return str(
            self.env["ir.ui.view"]._render_template(
                "runbot.nginx_config",
                {
                    "nginx_dir": "/tmp/nginx",
                    "runbot_static": "/tmp/static/",
                    "base_url": "http://runbot.example.com",
                    "re_escape": re.escape,
                    "host_name": "runbot.example.com",
                    "builds": builds,
                },
            )
        )

    def test_trusted_ips_come_from_the_parameter(self):
        self.env["ir.config_parameter"].sudo().set_param("runbot_ux.trusted_ips", "1.2.3.4, 5.6.7.8,")
        conf = self._render(self.Build)
        self.assertIn("  1.2.3.4 1;\n", conf)
        self.assertIn("  5.6.7.8 1;\n", conf)

    def test_without_parameter_nobody_is_trusted(self):
        conf = self._render(self.Build)
        geo = conf.split("geo $runbot_trusted {")[1].split("}")[0]
        self.assertEqual(geo.split(), ["default", "0;"])

    def test_ips_trusted_for_the_day(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("runbot_ux.trusted_ips", "1.2.3.4")
        params.set_param("runbot_ux.trusted_ips_today", "8.8.8.8")
        geo = self._render(self.Build).split("geo $runbot_trusted {")[1].split("}")[0]
        self.assertEqual(geo.split(), ["default", "0;", "1.2.3.4", "1;", "8.8.8.8", "1;"])

        self.env.ref("runbot_ux.ir_cron_clear_trusted_ips").method_direct_trigger()
        self.assertNotIn("8.8.8.8", self._render(self.Build))

    def test_live_build_blocks_code_writes(self):
        build = self.Build.create({"params_id": self.base_params.id, "port": 2000, "host": "runbot.example.com"})
        conf = self._render(build)
        self.assertIn("if ($runbot_trusted = 0) { return 418; }", conf)
        self.assertIn("proxy_pass http://127.0.0.1:2000;", conf)

    def test_short_link_keeps_the_client_scheme(self):
        build = self.Build.create({"params_id": self.base_params.id, "port": 2000, "host": "runbot.example.com"})
        server = next(block for block in self._render(build).split("server {") if "return 307" in block)
        returns = [line.strip() for line in server.splitlines() if line.strip().startswith("return 307")]
        self.assertTrue(returns[0].startswith("return 307 $real_scheme://"), returns)

    def test_build_menu_links(self):
        build = self.Build.create(
            {
                "params_id": self.base_params.id,
                "host": "runbot.example.com",
                "local_state": "running",
                "log_list": "run",
            }
        )
        menu = str(
            self.env["ir.ui.view"]._render_template("runbot.build_menu", {"bu": build, "fqdn": "frontend.example.com"})
        )
        self.assertIn('href="%srun.txt"' % build._http_log_url(), menu)
        self.assertTrue(build._http_log_url().startswith("https://runbot.example.com/"))
        self.assertNotIn("/web/database/selector", menu)


@tagged("-at_install", "post_install")
class TestTrustedIpPage(HttpCase):
    def test_only_public_ips_can_be_trusted(self):
        self.authenticate("admin", "admin")
        for ip in ("1.2.3.4; 0.0.0.0/0", "127.0.0.1", "10.0.0.1", "8.8.8.8"):
            self.url_open("/runbot/trusted_ip", data={"ip": ip, "csrf_token": http.Request.csrf_token(self)})
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param("runbot_ux.trusted_ips_today"), "8.8.8.8")
        self.assertEqual(
            self.env["ir.logging"].search([("message", "like", "trusted IP")]).mapped("message"),
            ["admin trusted IP 8.8.8.8 for today"],
        )
