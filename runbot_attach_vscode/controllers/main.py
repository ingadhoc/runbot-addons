import logging
import time
from urllib.parse import urlsplit

import requests
from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 4 * 3600


class VsCodeController(http.Controller):
    """Opens VS Code for a user and checks their access token.

    When an internal user clicks "Open VS Code", `/runbot/vscode/<id>` finds
    or creates that user's container, gives the browser a signed token, and
    sends them to their personal address `<dest>-vscode-<user_key>.<host>`.
    On every request to that address, nginx calls `auth_check` to make sure
    the token is valid, not expired, for this build, and belongs to the user
    who owns the address — so one user's token can never open another user's
    container. The token is built and checked by `runbot.token.signer`.
    """

    @staticmethod
    def _cookie_name(build_id):
        """Cookie holding the access token for one build. One per build so a
        user opening VS Code on a second build does not overwrite the first
        build's token."""
        return f"vscode_token_{build_id}"

    @http.route(
        ["/runbot/vscode/<int:build_id>"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def open_vscode(self, build_id):
        """Find or create the user's session, start its container, and send
        the browser to the user's personal VS Code address with an access
        token, which nginx stores there as a cookie."""
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
        # Reload nginx now instead of waiting for the builder's next cycle.
        # _reload_nginx only renders builds of this process's host name, so the
        # web process must run with the same forced_host_name as the builder.
        request.env["runbot.runbot"].sudo()._reload_nginx()
        session_url = build._vscode_session_url(session)
        if not self._wait_for_nginx(session_url):
            return request.render(
                "http_routing.http_error",
                {
                    "status_code": _("VS Code"),
                    "status_message": _("VS Code is not ready yet. Try again in a few seconds."),
                },
            )
        exp = int(time.time()) + TOKEN_TTL_SECONDS
        token = request.env["runbot.token.signer"]._make_token(build.id, request.env.user.id, exp)
        # Odoo may be served on another domain than build.host, so it cannot set
        # a cookie for the VS Code address: nginx sets it there (see
        # views/runbot_nginx.xml).
        return request.redirect(f"{session_url}/__vscode_login?token={token}", code=302, local=False)

    @staticmethod
    def _wait_for_nginx(session_url, timeout=5):
        """Wait until nginx serves the session's block; return False if it
        does not within `timeout`. The reload is not instant, and until then
        the build's Odoo answers the address. Only the session's block
        answers 400 to /__vscode_login without a token."""
        host = urlsplit(session_url).netloc
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = requests.get(
                    "http://127.0.0.1:8080/__vscode_login",
                    headers={"Host": host},
                    allow_redirects=False,
                    timeout=1,
                )
                if response.status_code == 400:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.2)
        _logger.warning("nginx did not serve %s after %ss", host, timeout)
        return False

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
        token = request.httprequest.cookies.get(self._cookie_name(build), "")
        if not token:
            return Response(status=401)
        try:
            expected_user_id = int(str(user).split("-", 1)[0])
        except (ValueError, TypeError):
            return Response(status=401)
        # parts are (build_id, user_id, exp); the signer already checked the
        # signature and expiry, here we check the token is for this build and user.
        parts = request.env["runbot.token.signer"]._verify_token(token)
        if not parts or len(parts) != 3:
            return Response(status=401)
        if int(parts[0]) != int(build) or int(parts[1]) != expected_user_id:
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
