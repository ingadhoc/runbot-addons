from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestRunbotTokenAuth(TransactionCase):
    """Signed access tokens: signature validity, tampering and expiry."""

    def test_token_verification(self):
        """A token returns its signed parts before expiry (so the caller can
        check build and user), and is rejected when tampered with or expired."""
        signer = self.env["runbot.token.signer"]
        token = signer._make_token(7, 42, 2**31)
        self.assertEqual(signer._verify_token(token), ["7", "42", str(2**31)])
        # a token whose payload and signature don't match must not verify: take
        # this token's payload but another token's signature.
        other = signer._make_token(8, 42, 2**31)
        forged = token.split(".")[0] + "." + other.split(".")[1]
        self.assertIsNone(signer._verify_token(forged))
        # expired token must not verify
        self.assertIsNone(signer._verify_token(signer._make_token(7, 42, 1)))

    def test_token_roundtrip_is_stable(self):
        """Every freshly made token returns the same parts. Guards against
        signature bytes being mistaken for the separator (the dot)."""
        signer = self.env["runbot.token.signer"]
        for build_id in range(1, 60):
            for user_id in range(1, 5):
                parts = signer._verify_token(signer._make_token(build_id, user_id, 2**31))
                self.assertEqual(
                    parts,
                    [str(build_id), str(user_id), str(2**31)],
                    f"token for build={build_id} user={user_id} failed to verify",
                )

    def test_user_key(self):
        """The shared per-user key is `<id>-<login-slug>`: the slug keeps only
        the part before the `@` and slugifies it, so the per-user container
        modules all land on the same handle. auth_check parses the leading id."""
        signer = self.env["runbot.token.signer"]
        user = self.env["res.users"].create({"name": "Key User", "login": "key.user@example.com"})
        self.assertEqual(signer._user_key(user), f"{user.id}-key-user")
        # a login with nothing slug-worthy falls back to the bare id.
        odd = self.env["res.users"].create({"name": "Odd", "login": "@@@"})
        self.assertEqual(signer._user_key(odd), str(odd.id))
