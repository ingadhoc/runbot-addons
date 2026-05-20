from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestRunbotAttachVscode(TransactionCase):
    """Covers reference_layer override, vscode_url compute and action_open_vscode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_layer = cls.env.ref("runbot_attach_vscode.docker_layer_code_server")

    def test_reference_layer_overrides_version(self):
        dockerfile = self.env["runbot.dockerfile"].create({"name": "test_attach_vscode_override"})
        self.env["runbot.docker_layer"].create(
            {
                "name": "cs_ref_override",
                "dockerfile_id": dockerfile.id,
                "layer_type": "reference_layer",
                "reference_docker_layer_id": self.source_layer.id,
                "values": {"CODE_SERVER_VERSION": "4.97.0"},
            }
        )
        self.assertIn("--version 4.97.0", dockerfile.dockerfile)
        self.assertNotIn("--version 4.96.4", dockerfile.dockerfile)

    def _new_build(self, dest=None, host=None):
        build = self.env["runbot.build"].new({})
        if dest is not None:
            build.dest = dest
        if host is not None:
            build.host = host
        build._compute_vscode_url()
        return build

    def test_vscode_url(self):
        """Compute: default ICP, override, and short-circuit when dest is missing."""
        # defaults (https / vscode)
        build = self._new_build(dest="12345-19-0-x", host="ci.example.com")
        self.assertEqual(build.vscode_url, "https://12345-19-0-x-vscode.ci.example.com")

        # ICP override
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("runbot_attach_vscode.scheme", "http")
        icp.set_param("runbot_attach_vscode.url_suffix", "ide")
        build = self._new_build(dest="42-x", host="ci.adhoc.local")
        self.assertEqual(build.vscode_url, "http://42-x-ide.ci.adhoc.local")

        # missing dest → short-circuit
        build = self._new_build(host="ci.example.com")
        self.assertFalse(build.vscode_url)

    def test_action_open_vscode_blocks_when_url_missing(self):
        build = self._new_build()
        with self.assertRaises(UserError):
            build.action_open_vscode()

    def test_action_open_vscode_blocks_portal_user(self):
        portal_user = self.env["res.users"].create(
            {
                "name": "Portal user",
                "login": "portal_attach_vscode",
                "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        build = self.env["runbot.build"].with_user(portal_user).new({})
        build.dest = "12345-19-0-x"
        build.host = "ci.example.com"
        build._compute_vscode_url()
        with self.assertRaises(UserError):
            build.action_open_vscode()
