##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

from odoo import models
from odoo.addons.runbot_merge import git

from ..autosquash import single_after_autosquash


class CheckCommits(models.Model):
    _inherit = "runbot_merge.pull_requests.check_commits"

    def _process_item(self):
        # as the base, which only counts the commits, but reading their
        # subjects to also know what the autosquash leaves
        pr_id = self.pull_request_id
        repo = git.get_local(pr_id.repository)
        target_head, pr_head = sorted(
            repo.fetch_heads(
                pr_id.repository,
                f"refs/heads/{pr_id.target.name}",
                pr_id.head,
            ),
            key=lambda h: h == pr_id.head,
        )
        log = (
            repo.stdout()
            .with_config(check=True, encoding="utf-8")
            .log("--reverse", "-z", "--format=%H%n%B", f"{target_head}..{pr_head}")
            .stdout
        )
        commits = [
            {"sha": sha, "commit": {"message": message}}
            for sha, message in (entry.lstrip("\n").split("\n", 1) for entry in filter(None, log.split("\0")))
        ]
        self._logger.info("%s: %s commits", pr_id.display_name, len(commits))
        pr_id.squash = len(commits) == 1
        pr_id.single_after_autosquash = single_after_autosquash(commits)
