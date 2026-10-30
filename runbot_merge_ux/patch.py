##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import json
import logging

from odoo.addons.runbot_merge import exceptions
from odoo.addons.runbot_merge.models import stagings_create

from .autosquash import (
    autosquash_range,
    fold_squash_messages,
    group_autosquash,
    has_autosquash_commits,
    single_after_autosquash,
)

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


def _rebase_autosquash(pr, info, commits, related_prs, merge=False):
    """Rebases ``commits`` on the staging head and squashes each ``fixup!`` and
    ``squash!`` commit into the commit it fixes.

    :param merge: put the "closes" footer on the commit that ends up last
    :returns: the new head and the mapping of each commit of the PR to the
              commit it ended up in
    """
    # fold the squash! messages before the mergebot adds its references, so
    # the footer is not added to a fixup
    groups = group_autosquash(commits)
    fold_squash_messages(groups)
    stagings_create.add_self_references(pr, commits, related_prs=related_prs, merge=merge and groups[-1][0])
    rebased, rebase_map = info.repo.rebase(info.head, commits=commits)
    head, squash_map, _ = autosquash_range(
        info.repo, info.head, rebased, original_shas={new: sha for sha, new in rebase_map.items()}
    )
    return head, {sha: squash_map[new] for sha, new in rebase_map.items()}


_original_stage_rebase_ff = stagings_create.stage_rebase_ff


def stage_rebase_ff(pr, info, commits, related_prs):
    if not has_autosquash_commits(commits):
        return _original_stage_rebase_ff(pr, info, commits, related_prs=related_prs)

    head, mapping = _rebase_autosquash(pr, info, commits, related_prs, merge=True)
    pr.commits_map = json.dumps({**mapping, "": head})
    return head


_original_stage_rebase_merge = stagings_create.stage_rebase_merge


def stage_rebase_merge(pr, info, commits, related_prs):
    if not has_autosquash_commits(commits):
        return _original_stage_rebase_merge(pr, info, commits, related_prs=related_prs)

    head, mapping = _rebase_autosquash(pr, info, commits, related_prs)
    msg = pr._build_message(pr, related_prs=related_prs)
    project = pr.repository.project_id
    merge_head = info.repo.merge(info.head, head, str(msg), author=(project.github_name, project.github_email))
    pr.commits_map = json.dumps({**mapping, "": merge_head})
    return merge_head


_original_stage_merge = stagings_create.stage_merge


def stage_merge(pr, info, commits, related_prs):
    # merge keeps the commits of the PR as they are, it cannot squash them
    if has_autosquash_commits(commits):
        raise exceptions.Unmergeable(
            pr,
            "has fixup! or squash! commits, which `merge` does not squash. Merge it with `rebase-ff` or"
            " `rebase-merge`, or squash them with `git rebase -i --autosquash` and push.",
        )
    return _original_stage_merge(pr, info, commits, related_prs=related_prs)


_original_validate_pr = stagings_create.validate_pr


def validate_pr(pr, info):
    # the field may come from the previous push if the check_commits job did
    # not run yet, so it is checked again on the commits being staged
    if not (
        pr.single_after_autosquash
        and not (pr.squash or pr.merge_method)
        and single_after_autosquash(info.gh.commits(pr.number))
    ):
        return _original_validate_pr(pr, info)
    # merged like a single commit PR, without storing a merge method that a
    # later push could make wrong
    pr.merge_method = "rebase-ff"
    try:
        return _original_validate_pr(pr, info)
    finally:
        pr.merge_method = False


def post_load():
    # Replace the original stage function
    stagings_create.stage = stage_with_bump_validation
    stagings_create.stage_rebase_ff = stage_rebase_ff
    stagings_create.stage_rebase_merge = stage_rebase_merge
    stagings_create.stage_merge = stage_merge
    stagings_create.validate_pr = validate_pr
    _logger.info("runbot_merge_ux patches applied (bump policy validation, autosquash)")
