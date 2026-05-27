from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..controllers.main import VsCodeController


@tagged("-at_install", "post_install")
class TestRunbotAttachVscode(TransactionCase):
    """code-server layer, vscode availability, per-user sessions and auth."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source_layer = cls.env.ref("runbot_attach_vscode.docker_layer_code_server")
        # Dockerfile + reference layer that vscode availability requires.
        cls.dockerfile_with_layer = cls.env["runbot.dockerfile"].create(
            {"name": "test_attach_vscode_dockerfile"},
        )
        cls.env["runbot.docker_layer"].create(
            {
                "name": "test_cs_ref",
                "dockerfile_id": cls.dockerfile_with_layer.id,
                "layer_type": "reference_layer",
                "reference_docker_layer_id": cls.source_layer.id,
            },
        )
        cls.version = cls.env["runbot.version"].search([("name", "=", "18.0")], limit=1) or cls.env[
            "runbot.version"
        ].create({"name": "18.0"})
        cls.project = cls.env.ref("runbot.main_project")
        cls.params = cls.env["runbot.build.params"].create(
            {
                "version_id": cls.version.id,
                "project_id": cls.project.id,
                "dockerfile_id": cls.dockerfile_with_layer.id,
            },
        )
        cls.user_a = cls.env["res.users"].create(
            {"name": "VS User A", "login": "vscode_user_a"},
        )
        cls.user_b = cls.env["res.users"].create(
            {"name": "VS User B", "login": "vscode_user_b"},
        )

    # --- helpers -----------------------------------------------------------

    def _new_build(self, dest=None, host=None, params=None):
        """Build kept only in memory, for checks that don't need to be saved."""
        build = self.env["runbot.build"].new({})
        build.params_id = params if params is not None else self.params
        build.local_state = "running"
        if dest is not None:
            build.dest = dest
        if host is not None:
            build.host = host
        build._compute_global_state()
        build._compute_vscode_available()
        return build

    def _persisted_build(self, host="ci.example.com"):
        build = self.env["runbot.build"].create({"params_id": self.params.id})
        build.write({"host": host, "local_state": "running"})
        return build

    # --- VS Code availability + URL ----------------------------------------

    def test_vscode_available(self):
        # with layer + dest + host → available
        build = self._new_build(dest="12345-19-0-x", host="ci.example.com")
        self.assertTrue(build.vscode_available)
        # no dest → not available
        self.assertFalse(self._new_build(host="ci.example.com").vscode_available)
        # dockerfile without the code-server layer → not available
        params_no_layer = self.env["runbot.build.params"].create(
            {
                "version_id": self.version.id,
                "project_id": self.project.id,
                "dockerfile_id": self.env["runbot.dockerfile"].create({"name": "no_layer"}).id,
            }
        )
        build = self._new_build(dest="42-x", host="ci.example.com", params=params_no_layer)
        self.assertFalse(build.vscode_available)

    def test_session_url_composition(self):
        build = self._new_build(dest="42-x", host="ci.adhoc.local")
        session = self.env["runbot.build.vscode.session"].new({"user_id": self.user_a.id})
        self.assertEqual(
            build._vscode_session_url(session),
            f"https://42-x-vscode-{session.user_key}.ci.adhoc.local",
        )
        # scheme and suffix come from settings
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("runbot_attach_vscode.scheme", "http")
        icp.set_param("runbot_attach_vscode.url_suffix", "ide")
        self.assertEqual(
            build._vscode_session_url(session),
            f"http://42-x-ide-{session.user_key}.ci.adhoc.local",
        )

    # --- session model -----------------------------------------------------

    def test_user_key_format(self):
        Session = self.env["runbot.build.vscode.session"]
        # login `vscode_user_a` becomes the key `vscode-user-a`
        session = Session.new({"user_id": self.user_a.id})
        self.assertEqual(session.user_key, f"{self.user_a.id}-vscode-user-a")
        # email login keeps only the part before the @
        email_user = self.env["res.users"].create(
            {"name": "Email User", "login": "email.user@example.com"},
        )
        email_session = Session.new({"user_id": email_user.id})
        self.assertEqual(email_session.user_key, f"{email_user.id}-email-user")

    def test_container_name(self):
        build = self._persisted_build()
        session = self.env["runbot.build.vscode.session"].create(
            {"build_id": build.id, "user_id": self.user_a.id},
        )
        self.assertTrue(session.container_name.startswith(build.dest))
        self.assertIn("_vscode_", session.container_name)
        self.assertIn(session.user_key, session.container_name)

    def test_find_free_port_avoids_used(self):
        build = self._persisted_build()
        s_a = self.env["runbot.build.vscode.session"].create(
            {"build_id": build.id, "user_id": self.user_a.id, "state": "running"},
        )
        s_a.port = self.env["runbot.build.vscode.session"]._find_free_port()
        s_b = self.env["runbot.build.vscode.session"].create(
            {"build_id": build.id, "user_id": self.user_b.id, "state": "running"},
        )
        s_b.port = self.env["runbot.build.vscode.session"]._find_free_port()
        self.assertNotEqual(s_a.port, s_b.port)
        self.assertGreaterEqual(s_a.port, 20000)

    def test_ensure_user_vscode_container_find_or_create(self):
        build = self._persisted_build()
        Session = self.env["runbot.build.vscode.session"]
        with patch.object(Session.__class__, "_ensure_container", return_value=None):
            s1 = build._ensure_user_vscode_container(self.user_a)
            s2 = build._ensure_user_vscode_container(self.user_a)
            self.assertEqual(s1, s2, "same user reuses the session")
            s3 = build._ensure_user_vscode_container(self.user_b)
            self.assertNotEqual(s1, s3, "different user gets a distinct session")
        sessions = build.vscode_session_ids
        self.assertEqual(len(sessions), 2)
        self.assertNotEqual(
            sessions[0].container_name,
            sessions[1].container_name,
            "each user's container is isolated",
        )

    # --- auth (the security-critical property) -----------------------------

    def test_token_verification(self):
        """Token must be rejected for the wrong user, the wrong build, or when
        expired, and accepted for the right (build, user) before expiry."""
        with patch.object(VsCodeController, "_vscode_secret", staticmethod(lambda: b"testkey")):
            token = VsCodeController._make_token(build_id=7, user_id=self.user_a.id, exp=2**31)
            self.assertTrue(VsCodeController._verify_token(token, 7, self.user_a.id))
            # signed for user A, must not validate for user B
            self.assertFalse(VsCodeController._verify_token(token, 7, self.user_b.id))
            # wrong build
            self.assertFalse(VsCodeController._verify_token(token, 8, self.user_a.id))
            # also valid when the user is not checked (build-only)
            self.assertTrue(VsCodeController._verify_token(token, 7))
            # expired token
            expired = VsCodeController._make_token(build_id=7, user_id=self.user_a.id, exp=1)
            self.assertFalse(VsCodeController._verify_token(expired, 7, self.user_a.id))

    def test_token_roundtrip_is_stable(self):
        """Every freshly made token must verify. Guards against signature bytes
        being mistaken for the separator (the dot)."""
        with patch.object(VsCodeController, "_vscode_secret", staticmethod(lambda: b"testkey")):
            for build_id in range(1, 60):
                for user_id in range(1, 5):
                    token = VsCodeController._make_token(build_id, user_id, 2**31)
                    self.assertTrue(
                        VsCodeController._verify_token(token, build_id, user_id),
                        f"token for build={build_id} user={user_id} failed to verify",
                    )

    # --- teardown ----------------------------------------------------------

    def test_kill_stops_sessions(self):
        build = self._persisted_build()
        self.env["runbot.build.vscode.session"].create(
            {"build_id": build.id, "user_id": self.user_a.id, "state": "running"},
        )
        with patch("odoo.addons.runbot.models.build.docker_stop"), patch(
            "odoo.addons.runbot_attach_vscode.models.runbot_build_vscode_session.subprocess.run"
        ):
            build._kill()
        self.assertEqual(build.vscode_session_ids.state, "dead")

    def test_cron_closes_unused_sessions(self):
        build = self._persisted_build()
        session = self.env["runbot.build.vscode.session"].create(
            {"build_id": build.id, "user_id": self.user_a.id, "state": "running"},
        )
        # Make it look untouched for far longer than the 4-hour limit.
        session.last_seen = "2000-01-01 00:00:00"
        with patch("odoo.addons.runbot_attach_vscode.models.runbot_build_vscode_session.subprocess.run"):
            self.env["runbot.build.vscode.session"]._cron_close_unused_sessions()
        self.assertFalse(session.exists(), "an unused session is closed and removed by the cron")
