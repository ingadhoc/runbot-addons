import base64
import hashlib
import hmac
import logging
import time

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

TOKEN_COOKIE = "vscode_token"
TOKEN_TTL_SECONDS = 4 * 3600


class VsCodeController(http.Controller):
    """Opens VS Code for a user and checks their access token.

    When an internal user clicks "Open VS Code", `/runbot/vscode/<id>` finds
    or creates that user's container, gives the browser a signed token, and
    sends them to their personal address `<dest>-vscode-<user_key>.<host>`.
    On every request to that address, nginx calls `auth_check` to make sure
    the token is valid, not expired, for this build, and belongs to the user
    who owns the address — so one user's token can never open another user's
    container.
    """

    @staticmethod
    def _vscode_secret():
        param = request.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not param:
            # database.secret may not be set yet; fall back to database.uuid so
            # we sign and check tokens with the same key even after a restart.
            param = request.env["ir.config_parameter"].sudo().get_param("database.uuid", "")
        return (param or "").encode()

    @staticmethod
    def _b64(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _unb64(text):
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    @classmethod
    def _make_token(cls, build_id, user_id, exp):
        payload = f"{int(build_id)}|{int(user_id)}|{int(exp)}".encode()
        sig = hmac.new(cls._vscode_secret(), payload, hashlib.sha256).digest()
        # Encode the two parts separately and join with a dot. The dot is safe
        # as a separator because urlsafe base64 never produces one, so the
        # signature's raw bytes can't be mistaken for it.
        return f"{cls._b64(payload)}.{cls._b64(sig)}"

    @classmethod
    def _verify_token(cls, token, build_id, user_id=None):
        """Check the token's signature and expiry, and that it is for this
        build. When `user_id` is given, also check the token belongs to that
        user."""
        try:
            body, mac = token.split(".", 1)
            payload = cls._unb64(body)
            sig = cls._unb64(mac)
            expected = hmac.new(cls._vscode_secret(), payload, hashlib.sha256).digest()
            if not hmac.compare_digest(sig, expected):
                return False
            tok_build, tok_user, exp = payload.decode().split("|")
            if int(tok_build) != int(build_id):
                return False
            if user_id is not None and int(tok_user) != int(user_id):
                return False
            if int(exp) < int(time.time()):
                return False
            return True
        except Exception:
            return False

    @http.route(
        ["/runbot/vscode/<int:build_id>"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def open_vscode(self, build_id):
        """Find or create the user's session, start its container, set the
        access token on Odoo's domain, and send the browser to the user's
        personal VS Code address."""
        if not request.env.user._is_internal():
            return request.not_found()
        build = request.env["runbot.build"].browse(build_id).sudo()
        if not build.exists() or not build.vscode_available:
            return request.not_found()
        if build.local_state != "running":
            return request.render(
                "http_routing.http_error",
                {
                    "status_code": _("Build not running"),
                    "status_message": _("Wake the build up before opening VS Code."),
                },
            )
        try:
            session = build._ensure_user_vscode_container(request.env.user)
        except UserError as exc:
            return request.render(
                "http_routing.http_error",
                {"status_code": _("VS Code"), "status_message": exc.args[0]},
            )
        # Reload nginx now so the new server block is live before the 302
        # fires; otherwise the request races the scheduler cycle and falls
        # through to the build's Odoo.
        request.env["runbot.runbot"].sudo()._reload_nginx()
        exp = int(time.time()) + TOKEN_TTL_SECONDS
        token = self._make_token(build.id, request.env.user.id, exp)
        response = request.redirect(build._vscode_session_url(session), code=302, local=False)
        # This token proves who the user is. We hand it out here (on Odoo's
        # host) but nginx checks it on the VS Code subdomain, so we tie it to
        # build.host to make the browser send it to both.
        response.set_cookie(
            TOKEN_COOKIE,
            token,
            max_age=TOKEN_TTL_SECONDS,
            domain=build.host,
            secure=True,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return response

    @http.route(
        ["/runbot/vscode/auth_check"],
        type="http",
        auth="public",
        csrf=False,
        sitemap=False,
    )
    def auth_check(self, build=None, user=None):
        """Called by nginx before every request to a VS Code address. Returns
        200 only when the token is valid for this build and belongs to the
        user who owns the address (`user` is the `<id>-<slug>` key, where
        `<slug>` comes from the login's local part). Also marks the session
        as recently used so the cleanup job leaves it alone."""
        if not build or not user:
            return Response(status=401)
        token = request.httprequest.cookies.get(TOKEN_COOKIE, "")
        if not token:
            return Response(status=401)
        try:
            expected_user_id = int(str(user).split("-", 1)[0])
        except (ValueError, TypeError):
            return Response(status=401)
        if not self._verify_token(token, build, expected_user_id):
            return Response(status=401)
        session = (
            request.env["runbot.build.vscode.session"]
            .sudo()
            .search(
                [("build_id", "=", int(build)), ("user_id", "=", expected_user_id)],
                limit=1,
            )
        )
        if session:
            session.touch()
        return Response(status=200)
