from unittest.mock import patch

from odoo.addons.runbot.tests.common import RunbotCase
from odoo.tests import tagged


@tagged("-at_install", "post_install")
class TestDraftBuilds(RunbotCase):
    """Tests for the builds of a bundle with a draft pr"""

    def _slot(self):
        """An empty slot on the bundle's batch, the way _prepare leaves it."""
        return self.env["runbot.batch.slot"].create(
            {
                "batch_id": self.dev_batch.id,
                "params_id": self.base_params.id,
                "trigger_id": self.trigger_server.id,
                "link_type": "created",
            }
        )

    def test_draft_pr_starts_no_build(self):
        self.dev_pr.draft = True
        slot = self._slot()
        self.dev_batch._start_builds()
        self.assertFalse(slot.build_id, "the pr is draft, nothing should build")

    def test_pr_out_of_draft_starts_the_build(self):
        self.dev_pr.draft = False
        slot = self._slot()
        self.dev_batch._start_builds()
        self.assertTrue(slot.build_id, "the pr is not draft, it builds as usual")

    def _commit(self, name, repo):
        return self.Commit.create({"name": name * 40, "repo_id": repo.id})

    def _pushed_batch(self, commit, build=False):
        """A past batch of the bundle where the commit arrived by a push."""
        batch = self.Batch.create(
            {
                "bundle_id": self.dev_bundle.id,
                "state": "done",
                "commit_link_ids": [(0, 0, {"commit_id": commit.id, "match_type": "new"})],
            }
        )
        self.env["runbot.batch.slot"].create(
            {
                "batch_id": batch.id,
                "params_id": self.base_params.id,
                "trigger_id": self.trigger_server.id,
                "link_type": "created",
                "build_id": build and self.Build.create({"params_id": self.base_params.id}).id,
            }
        )
        return batch

    def _leave_draft(self):
        """Take the pr out of draft the way the github hook does, and return the batch it forces."""
        self.dev_bundle.last_batch.state = "done"
        with patch(
            "odoo.addons.runbot.models.branch.Branch._update_branch_infos",
            lambda branch, payload=None: branch.write({"draft": False}),
        ):
            self.dev_pr._recompute_infos()
        return self.dev_bundle.last_batch

    def test_head_built_before_draft_is_new_again(self):
        """Pushed and built, then draft, then out of draft: the head builds again as new."""
        commit = self._commit("a", self.repo_server)
        self.dev_pr.head = commit
        self.dev_bundle.last_batch = self._pushed_batch(commit, build=True)
        self.dev_pr.draft = True
        batch = self._leave_draft()
        self.assertEqual(batch.commit_link_ids.mapped("match_type"), ["new"])
        self.assertEqual(batch.commit_link_ids.commit_id, commit)

    def test_every_repo_of_the_bundle_is_new(self):
        """In a bundle with two repos, both heads build again, not only the one of the draft pr."""
        server_commit = self._commit("a", self.repo_server)
        addons_commit = self._commit("b", self.repo_addons)
        self.Branch.create(
            {
                "name": self.dev_bundle.name,
                "bundle_id": self.dev_bundle.id,
                "is_pr": False,
                "remote_id": self.remote_addons.id,
                "head": addons_commit.id,
            }
        )
        self.dev_pr.write({"head": server_commit.id, "draft": True})
        self.dev_bundle.last_batch = self._pushed_batch(server_commit)
        batch = self._leave_draft()
        self.assertEqual(set(batch.commit_link_ids.mapped("match_type")), {"new"})
        self.assertEqual(batch.commit_link_ids.commit_id, server_commit | addons_commit)
