import logging
import time

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 8 * 3600
COOKIE_NAME = "opencode_token"


class OpencodeController(http.Controller):
    """Opens a user's OpenCode workspace and checks their access token.

    "OpenCode" in the user menu hits `/runbot/opencode`, which finds or creates
    the user's workspace, hands the browser a signed token, and sends them to
    their personal address `opencode-<user_key>.<host>`. nginx then calls
    `auth_check` before every request to that address, so one user's token can
    never open another user's workspace. The token is built and checked by
    `runbot.token.signer`.
    """

    @http.route(
        ["/runbot/opencode"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def open_opencode(self):
        """Find or create the user's workspace, start its container, set the
        access token, and send the browser to their personal address."""
        if not request.env.user._is_internal():
            return request.not_found()
        host = request.env["runbot.host"]._get_current_name()
        try:
            workspace = request.env["runbot.opencode.workspace"].sudo()._ensure_workspace(request.env.user)
        except UserError as exc:
            return request.render(
                "http_routing.http_error",
                {"status_code": _("OpenCode"), "status_message": exc.args[0]},
            )
        # Reload nginx so the new server block is live before the redirect
        # fires. Single-host assumption.
        request.env["runbot.runbot"].sudo()._reload_nginx()
        exp = int(time.time()) + TOKEN_TTL_SECONDS
        token = request.env["runbot.token.signer"]._make_token(request.env.user.id, exp)
        # Same address the container is told it serves at (see _get_public_url).
        url = workspace._get_public_url()
        response = request.redirect(url, code=302, local=False)
        # We hand the token out here (on Odoo's host) but nginx checks it on the
        # OpenCode subdomain, so tie it to `host` to make the browser send it.
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=TOKEN_TTL_SECONDS,
            domain=host,
            secure=True,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return response

    @http.route(
        ["/runbot/opencode/auth_check"],
        type="http",
        auth="public",
        csrf=False,
        sitemap=False,
    )
    def auth_check(self, user=None):
        """Called by nginx before every request to an OpenCode address. Returns
        200 only when the token is valid and belongs to the user who owns the
        address (`user` is the `<id>-<slug>` key). Also marks the workspace as
        recently used so the cleanup job leaves it alone."""
        if not user:
            return Response(status=401)
        token = request.httprequest.cookies.get(COOKIE_NAME, "")
        if not token:
            return Response(status=401)
        try:
            expected_user_id = int(str(user).split("-", 1)[0])
        except (ValueError, TypeError):
            return Response(status=401)
        # parts are (user_id, exp); the signer already checked the signature and
        # expiry, here we check the token belongs to the user owning the address.
        parts = request.env["runbot.token.signer"]._verify_token(token)
        if not parts or len(parts) != 2 or int(parts[0]) != expected_user_id:
            return Response(status=401)
        workspace = (
            request.env["runbot.opencode.workspace"].sudo().search([("user_id", "=", expected_user_id)], limit=1)
        )
        if workspace:
            workspace.touch()
        return Response(status=200)
