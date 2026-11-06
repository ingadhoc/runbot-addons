from unittest.mock import patch

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval


@tagged("-at_install", "post_install")
class TestCheckLicenses(RunbotCase):
    """Tests for RunbotBuild._check_licenses"""

    def setUp(self):
        super().setUp()
        params = self.base_params.copy({"trigger_id": self.trigger_addons.id})
        self.build = self.Build.create({"params_id": params.id})
        self.start_patcher(
            "build_checkout",
            "odoo.addons.runbot.models.build.BuildResult._checkout",
            return_value={},
        )
        self.repo_private = self.Repo.create({"name": "private", "project_id": self.project.id, "private": True})
        # repo_odoo stands for odoo and enterprise, repo_enterprise for one of ours, public.
        self.manifests = {
            "base": (self.repo_odoo, {"license": "LGPL-3"}),
            "account_accountant": (self.repo_odoo, {"license": "OEEL-1", "depends": ["base"]}),
            "saas_client": (self.repo_private, {"license": "LGPL-3", "depends": ["base"]}),
            "sale_ux": (self.repo_enterprise, {"license": "AGPL-3", "depends": ["base"]}),
        }

    def _check(self):
        with patch(
            "odoo.addons.runbot_ux.models.runbot_build.RunbotBuild._get_manifests",
            return_value=self.manifests,
        ):
            self.build._check_licenses()
        return self.build.log_ids.filtered(lambda log: log.level == "ERROR").mapped("message")

    def test_no_enterprise(self):
        self.assertEqual(self._check(), [])
        self.assertEqual(self.build.local_result, "ok")

    def test_agpl_in_public_repo_reaches_enterprise(self):
        self.manifests["account_ux"] = (self.repo_enterprise, {"license": "LGPL-3", "depends": ["account_accountant"]})
        self.manifests["account_report_ux"] = (self.repo_enterprise, {"license": "AGPL-3", "depends": ["account_ux"]})
        errors = sorted(self._check())
        self.assertEqual(len(errors), 3)
        # The chain shows how a module reaches Enterprise through one of ours.
        self.assertEqual(
            errors[0],
            "account_report_ux depends on Odoo Enterprise "
            "(account_report_ux -> account_ux -> account_accountant), and AGPL-3 can not be combined with OEEL-1. "
            "Fix: set 'license': 'LGPL-3' in its __manifest__.py.",
        )
        self.assertEqual(
            errors[1],
            "account_report_ux depends on Odoo Enterprise (account_report_ux -> account_ux -> account_accountant), "
            "but its repo enterprise is public. Fix: remove that dependency, or move the module to a private repo.",
        )
        self.assertIn("(account_ux -> account_accountant), but its repo enterprise is public", errors[2])
        self.assertEqual(self.build.local_result, "ko")

    def test_public_repo_depends_on_private_repo(self):
        self.manifests["sale_saas"] = (self.repo_enterprise, {"license": "LGPL-3", "depends": ["saas_client"]})
        self.assertEqual(
            self._check(),
            [
                "sale_saas depends on the private repo private (sale_saas -> saas_client), but its repo enterprise "
                "is public. Fix: remove that dependency, or move the module to a private repo."
            ],
        )

    def test_lgpl_in_private_repo_reaches_enterprise(self):
        self.manifests["account_ux"] = (self.repo_enterprise, {"license": "LGPL-3", "depends": ["account_accountant"]})
        self.repo_enterprise.private = True
        self.assertEqual(self._check(), [])
        self.assertEqual(self.build.local_result, "ok")

    def test_skip_keeps_the_agpl_rule(self):
        self.manifests["account_ux"] = (self.repo_enterprise, {"license": "AGPL-3", "depends": ["account_accountant"]})
        self.manifests["sale_saas"] = (self.repo_enterprise, {"license": "LGPL-3", "depends": ["saas_client"]})
        self.repo_enterprise.skip_private_dependency_check = True
        errors = self._check()
        self.assertEqual(len(errors), 1)
        self.assertTrue(
            errors[0].startswith("account_ux depends on Odoo Enterprise (account_ux -> account_accountant), and AGPL-3")
        )

    def test_not_installable_is_skipped(self):
        self.manifests["account_ux"] = (
            self.repo_enterprise,
            {"license": "AGPL-3", "depends": ["account_accountant"], "installable": False},
        )
        self.assertEqual(self._check(), [])

    def test_dependency_repos_are_not_checked(self):
        # Enterprise itself reaches Enterprise, but it is not a repo of the trigger.
        self.manifests["account_reports"] = (self.repo_odoo, {"license": "OEEL-1", "depends": ["account_accountant"]})
        self.assertEqual(self._check(), [])

    def test_step_runs_from_version_20(self):
        step = self.env.ref("runbot_ux.build_config_step_license_check")
        domain = safe_eval(step.domain_filter)
        for version, runs in (("18.0", False), ("20.0", True), ("master", True)):
            params = self.base_params.copy({"version_id": self.Version._get(version).id})
            build = self.Build.create({"params_id": params.id})
            self.assertEqual(bool(build.filtered_domain(domain)), runs, version)
