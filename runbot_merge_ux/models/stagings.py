##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class Stagings(models.Model):
    _inherit = "runbot_merge.stagings"

    def _safety_dance(self, gh):
        """Extended safety dance that includes version bumping after successful merge."""
        result = super()._safety_dance(gh)
        try:
            self._post_merge_version_bump(gh)
        except Exception as e:
            _logger.error("Error in post-merge version bump: %s", e, exc_info=True)
        return result

    def _post_merge_version_bump(self, gh):
        """Perform version bump after successful merge."""
        # Find PRs that require version bumps
        bump_prs = self.mapped("batch_ids.prs").filtered(lambda pr: pr.bump_policy == "bump")

        if not bump_prs:
            return

        _logger.info("Processing version bumps for PRs: %s", bump_prs.mapped("display_name"))

        # Group PRs by repository
        repos_prs = {}
        for pr in bump_prs:
            if pr.repository not in repos_prs:
                repos_prs[pr.repository] = self.env["runbot_merge.pull_requests"]
            repos_prs[pr.repository] |= pr

        # Process each repository
        for repository, prs in repos_prs.items():
            try:
                prs._bump_versions_in_repository(repository, gh[repository.name])
            except Exception as e:
                _logger.error(f"Failed to bump versions in {repository.name}: {e}", exc_info=True)
                for pr in prs:
                    self.env.ref("runbot_merge_ux.command.version_bump_failure")._send(
                        repository=pr.repository,
                        pull_request=pr.number,
                        format_args={"error_message": str(e), "pr": pr},
                    )
