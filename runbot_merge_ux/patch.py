##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import logging

from odoo.addons.runbot_merge import exceptions
from odoo.addons.runbot_merge.models import stagings_create

_logger = logging.getLogger(__name__)

# Monkey patch the stage function to add bump_policy validation
_original_stage = stagings_create.stage


def stage_with_bump_validation(pr, info, related_prs=()):
    """Enhanced stage function that validates bump_policy before staging"""
    # Check bump policy similar to merge_method validation
    if not pr.bump_policy:
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


def post_load():
    # Replace the original stage function
    stagings_create.stage = stage_with_bump_validation
    _logger.info("Bump policy monkey patch applied successfully via post_load!")
