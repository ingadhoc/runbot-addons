import logging

import requests
from odoo import fields, models

_logger = logging.getLogger(__name__)


class RunbotVersion(models.Model):
    _inherit = "runbot.version"

    modules_auto_install_enabled = fields.Text(
        readonly=True,
        help="Comma-separated modules forced to auto-install for this version. "
        "Synced daily from the provider (adhoc.module.module) and injected into "
        "each build's odoorc so builds match client bases.",
    )
    modules_auto_install_disabled = fields.Text(
        readonly=True,
        help="Comma-separated modules whose auto-install is disabled for this version. "
        "Synced daily from the provider (adhoc.module.module) and injected into "
        "each build's odoorc so builds match client bases.",
    )

    def _cron_fetch_auto_install_data(self):
        """Sync each version's auto-install policy from the provider. On error the
        previous value is kept."""
        provider_url = self.env["ir.config_parameter"].get_param("runbot_ux.provider_url")
        token = self.env["ir.config_parameter"].get_param("runbot_ux.provider_token")
        if not provider_url or not token:
            _logger.warning("runbot_ux: provider_url/token not configured; skipping auto-install sync")
            return

        endpoint = provider_url.rstrip("/") + "/saas_provider/get_runbot_auto_install_data"
        for version in self.search([("name", "!=", "master")]):
            try:
                response = requests.post(
                    endpoint,
                    json={"jsonrpc": "2.0", "method": "call", "params": {"major_version": version.name}},
                    headers={"token": token},
                    timeout=30,
                )
                response.raise_for_status()
                result = response.json().get("result") or {}
                if result.get("error"):
                    raise ValueError(result["error"])
            except Exception as e:
                _logger.warning("runbot_ux: could not sync auto-install data for %s: %s", version.name, e)
                continue  # keep last known good value

            version.write(
                {
                    "modules_auto_install_enabled": ",".join(result.get("enabled", [])),
                    "modules_auto_install_disabled": ",".join(result.get("disabled", [])),
                }
            )
