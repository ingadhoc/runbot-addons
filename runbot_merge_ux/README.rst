================
Runbot Merge UX
================

Automatic Version Bumping
=========================

This module extends runbot_merge to automatically bump addon versions after merging pull requests.

Features
--------

* Automatically increments addon versions in ``__manifest__.py`` after PR merge
* Command-based control via PR comments (``bump`` / ``nobump`` / ``bumped``)
* Manual retry button for failed version bumps
* Success/failure notifications posted to PRs
* Provider notification system for bump failures
* Only bumps addons that were modified in the PR

Usage
-----

Setting bump policy
~~~~~~~~~~~~~~~~~~~

Add a comment to your PR to enable version bumping for all modified modules::

    @mergebot bump

To bump only specific modules, use a comma-separated list::

    @mergebot bump=sale,purchase

To disable version bumping::

    @mergebot nobump

The version bump happens automatically after merge if the PR has ``bump`` policy.

Manual retry
~~~~~~~~~~~~

If an automatic version bump fails:

1. A notification will be posted to the PR
2. The provider will be notified via webhook
3. Use the **Retry Version Bump** button in the PR form to retry
4. Or manually bump the version and mark as done with::

    @mergebot bumped

Version Format
--------------

Versions follow the pattern: ``series.major.minor.patch``

When bumping:

* Minor version increments by 1
* Patch version resets to 0

Example: ``18.0.1.2.3`` → ``18.0.1.3.0``

Technical Details
-----------------

* Version bumps are pushed as a separate commit after merge
* Failed bumps notify the provider via JSONRPC endpoint
* Manual retry available through UI button or ``bumped`` command
* Uses git tree operations for efficient commits

Configuration
-------------

Provider Notification
~~~~~~~~~~~~~~~~~~~~~

Configure these parameters on the runbot instance:

* ``saas_client.provider_url``: Provider base URL
* ``saas_provider.odoo_project_token``: Authentication token

The provider should implement the ``/runbot_merge/version_bump_failure`` endpoint.
