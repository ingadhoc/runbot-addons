import re

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.exceptions import ValidationError
from odoo.tests import tagged


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
        self.env["ir.config_parameter"].sudo().set_param("runbot_ux.trusted_ips", "1.2.3.4")
        self.env["runbot.trusted.ip"].create([{"ip": "1.2.3.4"}, {"ip": "8.8.8.8"}])
        geo = self._render(self.Build).split("geo $runbot_trusted {")[1].split("}")[0]
        self.assertEqual(geo.split(), ["default", "0;", "1.2.3.4", "1;", "8.8.8.8", "1;"])

        self.env["runbot.trusted.ip"]._cron_clear()
        self.assertNotIn("8.8.8.8", self._render(self.Build))

    def test_only_public_ips_can_be_trusted(self):
        for ip in ("1.2.3.4; 0.0.0.0/0", "127.0.0.1", "10.0.0.1"):
            with self.subTest(ip=ip), self.assertRaises(ValidationError):
                self.env["runbot.trusted.ip"].create({"ip": ip})

    def test_live_build_blocks_code_writes(self):
        build = self.Build.create({"params_id": self.base_params.id, "port": 2000, "host": "runbot.example.com"})
        conf = self._render(build)
        self.assertIn("if ($runbot_trusted = 0) { return 418; }", conf)
        self.assertIn("proxy_pass http://127.0.0.1:2000;", conf)
