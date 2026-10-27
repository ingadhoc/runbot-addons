##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import json
import logging

from odoo.addons.runbot_merge import exceptions
from odoo.addons.runbot_merge.models import stagings_create

from .autosquash import fold_squash_messages, group_fixups, squash_fixups

_logger = logging.getLogger(__name__)

# Monkey patch the stage function to add bump_policy validation
_original_stage = stagings_create.stage


def stage_with_bump_validation(pr, info, related_prs=()):
    """Enhanced stage function that validates bump_policy before staging"""
    # Use PR-level policy, falling back to project default
    effective_policy = pr.bump_policy or pr.repository.project_id.default_bump_policy
    if not effective_policy:
        if not pr.bump_warned:
            # Use the same pattern as merge_method notification
            pr.env.ref("runbot_merge_ux.pr.bump_policy")._send(
                repository=pr.repository,
                pull_request=pr.number,
                format_args={"pr": pr},
            )
            pr.bump_warned = True
        raise exceptions.Skip()

    # Call original stage function
    return _original_stage(pr, info, related_prs)


_original_stage_rebase_ff = stagings_create.stage_rebase_ff


def stage_rebase_ff(pr, info, commits, related_prs):
    if not pr.autosquash:
        return _original_stage_rebase_ff(pr, info, commits, related_prs=related_prs)

    # fold the squash! messages before the mergebot adds its references, and
    # put the "closes" footer on the commit that ends up last, not on a fixup
    groups = group_fixups(commits)
    fold_squash_messages(groups)
    stagings_create.add_self_references(pr, commits, related_prs=related_prs, merge=groups[-1][0])
    rebased, rebase_map = info.repo.rebase(info.head, commits=commits)
    head, squash_map, _ = squash_fixups(
        info.repo, info.head, rebased, original_shas={new: sha for sha, new in rebase_map.items()}
    )
    pr.commits_map = json.dumps({**{sha: squash_map[new] for sha, new in rebase_map.items()}, "": head})
    return head


_original_validate_pr = stagings_create.validate_pr


def validate_pr(pr, info):
    # also the fixup! commits pushed after the missing merge method warning
    if not (pr.squash or pr.merge_method):
        pr._default_autosquash(info.gh.commits(pr.number))
    return _original_validate_pr(pr, info)


def post_load():
    # Replace the original stage function
    stagings_create.stage = stage_with_bump_validation
    stagings_create.stage_rebase_ff = stage_rebase_ff
    stagings_create.validate_pr = validate_pr
    _logger.info("runbot_merge_ux patches applied (bump policy validation, rebase-autosquash, default autosquash)")
