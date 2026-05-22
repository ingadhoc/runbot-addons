import base64
import hashlib
import hmac
import logging
import time

from odoo import _, http
from odoo.addons.runbot.container import docker_state
from odoo.exceptions import UserError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

TOKEN_COOKIE = "vscode_token"
TOKEN_TTL_SECONDS = 4 * 3600


class VsCodeController(http.Controller):
    """code-server entry-point + auth_check used by the per-build nginx block.

    The session model: when an internal user clicks "Open VS Code", the
    `/runbot/vscode/<id>` route issues an HMAC-signed cookie scoped to
    the parent domain (so the browser sends it on the <dest>-vscode.<host>
    subdomain). The runbot internal nginx block runs `auth_request` on
    every request to that subdomain — the sub-request hits
    `/runbot/vscode/auth_check?build=<id>` and validates the cookie. No
    valid cookie ⇒ 401 ⇒ nginx redirects back to /runbot/vscode/<id>,
    which re-issues (or bounces to /web/login if no session).
    """

    @staticmethod
    def _vscode_secret():
        param = request.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not param:
            # database.secret is initialized lazily; fall back to the cookie
            # key so verify-after-restart still works deterministically.
            param = request.env["ir.config_parameter"].sudo().get_param("database.uuid", "")
        return (param or "").encode()

    @classmethod
    def _make_token(cls, build_id, user_id, exp):
        payload = f"{int(build_id)}|{int(user_id)}|{int(exp)}".encode()
        sig = hmac.new(cls._vscode_secret(), payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + sig).decode().rstrip("=")

    @classmethod
    def _verify_token(cls, token, build_id):
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            payload, sig = raw.rsplit(b".", 1)
            expected = hmac.new(cls._vscode_secret(), payload, hashlib.sha256).digest()
            if not hmac.compare_digest(sig, expected):
                return False
            tok_build, _tok_user, exp = payload.decode().split("|")
            if int(tok_build) != int(build_id):
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
        """Issue the auth cookie + start code-server lazily + redirect.

        Both the backend "Open VS Code" button and the frontend dropdown
        funnel through this route so the cookie can be set on the parent
        domain (model methods can't attach cookies to act_url responses).
        """
        if not request.env.user._is_internal():
            return request.not_found()
        build = request.env["runbot.build"].browse(build_id).sudo()
        if not build.exists() or not build.vscode_url:
            return request.not_found()
        container_name = build._get_docker_name()
        if docker_state(container_name, build._path()) != "RUNNING":
            return request.render(
                "http_routing.http_error",
                {
                    "status_code": _("Build not running"),
                    "status_message": _("Wake the build up before opening VS Code."),
                },
            )
        try:
            build._ensure_code_server_running(container_name)
        except UserError as exc:
            return request.render(
                "http_routing.http_error",
                {"status_code": _("VS Code"), "status_message": exc.args[0]},
            )
        exp = int(time.time()) + TOKEN_TTL_SECONDS
        token = self._make_token(build.id, request.env.user.id, exp)
        response = request.redirect(build.vscode_url, code=302, local=False)
        # Setting Domain= to the build's host scopes the cookie to that
        # host *and* all subdomains under it (RFC 6265), which is exactly
        # what we need: Odoo runs on <host>, code-server is reached on
        # <dest>-vscode.<host>, and the browser sends the cookie to both.
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
    def auth_check(self, build=None):
        """Sub-request target for nginx `auth_request`. Returns 200 only when
        the request carries a valid, non-expired token cookie for the given
        build. nginx forwards the browser's Cookie header automatically."""
        if not build:
            return Response(status=401)
        token = request.httprequest.cookies.get(TOKEN_COOKIE, "")
        if not token:
            return Response(status=401)
        if self._verify_token(token, build):
            return Response(status=200)
        return Response(status=401)
