import base64
import hashlib
import hmac
import re
import time

from odoo import models


class RunbotTokenSigner(models.AbstractModel):
    """Signed access tokens shared by the runbot per-user container modules.

    A token is `<payload>.<signature>`, both urlsafe base64. The payload is the
    given parts joined by `|`; the signature is an HMAC over it with the database
    secret. By convention the last part is the expiry timestamp. Each module
    decides which parts to put in and check (e.g. build+user+exp, or user+exp);
    this model only signs them and validates the signature and expiry.
    """

    _name = "runbot.token.signer"
    _description = "Runbot signed access token"

    def _user_key(self, user):
        """Public per-user handle `<id>-<login-slug>` used in the workspace
        subdomain and the shared host folder. Both per-user container modules
        derive it the same way so they land on the same folder; auth_check only
        relies on the leading `<id>-`, the slug is just there to keep it readable."""
        local_part = (user.login or "").split("@")[0]
        slug = re.sub(r"[^a-z0-9]+", "-", local_part.lower()).strip("-")
        return f"{user.id}-{slug}" if slug else str(user.id)

    def _secret(self):
        """Key used to sign tokens: the database secret, or the database uuid as
        a fallback so the key survives a restart even if the secret is unset."""
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return (get_param("database.secret") or get_param("database.uuid", "")).encode()

    @staticmethod
    def _b64(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _unb64(text):
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def _make_token(self, *parts):
        """Sign a token from `parts` (integers); the last part is the expiry."""
        payload = "|".join(str(int(p)) for p in parts).encode()
        sig = hmac.new(self._secret(), payload, hashlib.sha256).digest()
        # The dot is a safe separator: urlsafe base64 never produces one, so the
        # signature's bytes can't be mistaken for it.
        return f"{self._b64(payload)}.{self._b64(sig)}"

    def _verify_token(self, token):
        """Return the token's parts (list of strings) when the signature is valid
        and it has not expired; otherwise None. The caller checks the parts
        (build, user, ...) are the ones it expects."""
        try:
            body, mac = token.split(".", 1)
            payload = self._unb64(body)
            sig = self._unb64(mac)
            expected = hmac.new(self._secret(), payload, hashlib.sha256).digest()
            if not hmac.compare_digest(sig, expected):
                return None
            parts = payload.decode().split("|")
            if int(parts[-1]) < int(time.time()):
                return None
            return parts
        except Exception:
            return None
