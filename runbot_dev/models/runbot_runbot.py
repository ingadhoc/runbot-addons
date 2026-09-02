import logging
import os
import shutil
import subprocess

from odoo import api, models
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Base version branch and a feature branch on top of it, so the local project
# has the same shape as production: a base bundle plus a bundle that gets built.
# The feature branch follows the house convention, <version>-t-<task>-<initials>.
BASE_BRANCH = "18.0"
FEATURE_BRANCH = "18.0-t-99999-dev"

# Each remote is named after the runbot.repo that fetches from it, so the
# mapping needs no explaining.
SERVER_REMOTE = "adhoc-cicd-odoo-odoo"
ENTERPRISE_REMOTE = "adhoc-cicd-odoo-enterprise"
ADDONS_REMOTE = "ingadhoc-dev"


class Runbot(models.AbstractModel):
    _inherit = "runbot.runbot"

    def _dev_remotes_path(self):
        """Directory holding the git remotes this runbot fetches from: what
        GitHub is in production. Set the runbot_dev.remotes_path system
        parameter to put them somewhere else."""
        param = self.env["ir.config_parameter"].sudo().get_param("runbot_dev.remotes_path")
        return param or os.path.join(config["data_dir"], "runbot-dev", "remotes")

    def _dev_odoo_path(self):
        """Root of the odoo sources this server runs from."""
        import odoo

        return os.path.dirname(os.path.dirname(os.path.abspath(odoo.__file__)))

    def _dev_enterprise_path(self):
        """Root of the enterprise sources, a sibling of the odoo ones in the
        house layout. Override with the runbot_dev.enterprise_path parameter."""
        param = self.env["ir.config_parameter"].sudo().get_param("runbot_dev.enterprise_path")
        return param or os.path.join(os.path.dirname(self._dev_odoo_path()), "enterprise")

    @api.model
    def _create_dev_data(self):
        """Materialize the remotes and point the demo records at them. They are
        local paths that differ per machine, so they cannot go in the xml."""
        self.env.ref("runbot_dev.remote_adhoc_cicd_odoo").name = self._create_dev_snapshot_remote(
            SERVER_REMOTE, self._dev_odoo_path(), "odoo-bin"
        )
        self.env.ref("runbot_dev.remote_adhoc_cicd_enterprise").name = self._create_dev_snapshot_remote(
            ENTERPRISE_REMOTE, self._dev_enterprise_path(), "web_enterprise/__manifest__.py"
        )
        self.env.ref("runbot_dev.remote_ingadhoc_dev").name = self._create_dev_addons_remote()

    def _create_dev_snapshot_remote(self, remote_name, work_tree, expected_file):
        """Snapshot a source tree into a git repo of its own.

        The local clones cannot be used as remotes: they are partial (filter
        blob:none) and git refuses to lazily fetch missing objects while serving
        upload-pack, so the mirror comes out with zero refs. Committing the work
        tree into a separate repo gives runbot every object it needs, with one
        commit and no network. Idempotent.
        """
        remotes = self._dev_remotes_path()
        bare = os.path.join(remotes, "%s.git" % remote_name)
        if os.path.isdir(bare):
            _logger.info("Snapshot %s already at %s, left as is", remote_name, bare)
            return bare

        if not os.path.isfile(os.path.join(work_tree, expected_file)):
            _logger.warning(
                "No %s at %s: the %s repo will have nothing to fetch",
                expected_file,
                work_tree,
                remote_name,
            )
        os.makedirs(remotes, exist_ok=True)
        self._dev_git(remotes, "init", "-q", "--bare", bare)
        self._dev_git(remotes, "--git-dir", bare, "symbolic-ref", "HEAD", "refs/heads/%s" % BASE_BRANCH)
        git_env = {**os.environ, "GIT_DIR": bare, "GIT_WORK_TREE": work_tree}
        self._dev_git(work_tree, "add", "-A", env=git_env)
        self._dev_git(work_tree, "commit", "-q", "-m", "%s %s snapshot" % (remote_name, BASE_BRANCH), env=git_env)
        _logger.info("Snapshot %s created at %s from %s", remote_name, bare, work_tree)
        return bare

    def _create_dev_addons_remote(self):
        """Create a git repo out of the modules in fixture_modules/, plus a work
        clone next to it to commit into. Idempotent: an existing repo is left
        alone so local commits survive a module update."""
        remotes = self._dev_remotes_path()
        bare = os.path.join(remotes, "%s.git" % ADDONS_REMOTE)
        work = os.path.join(remotes, ADDONS_REMOTE)
        if os.path.isdir(bare):
            _logger.info("Addons remote already at %s, left as is", bare)
            return bare

        source = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixture_modules")
        os.makedirs(remotes, exist_ok=True)
        self._dev_git(remotes, "init", "-q", "--bare", bare)
        self._dev_git(remotes, "clone", "-q", bare, work)
        for module in sorted(os.listdir(source)):
            shutil.copytree(os.path.join(source, module), os.path.join(work, module))
        self._dev_git(work, "add", "-A")
        self._dev_git(work, "commit", "-qm", "[ADD] fixture modules")
        self._dev_git(work, "branch", "-M", BASE_BRANCH)
        self._dev_git(work, "push", "-q", "origin", BASE_BRANCH)
        self._dev_git(work, "checkout", "-qb", FEATURE_BRANCH)
        self._dev_git(work, "commit", "-q", "--allow-empty", "-m", "[IMP] fixture modules: branch to build")
        self._dev_git(work, "push", "-q", "origin", FEATURE_BRANCH)
        _logger.info("Addons remote created at %s", bare)
        return bare

    def _dev_git(self, cwd, *args, env=None):
        subprocess.run(
            ["git", "-c", "user.name=runbot dev", "-c", "user.email=runbot-dev@example.com", *args],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
        )
