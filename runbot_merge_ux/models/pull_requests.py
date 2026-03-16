##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import ast
import json
import logging
import os
import re
import shutil
import tempfile

import requests
from odoo import fields, models
from odoo.addons.runbot_merge import git

_logger = logging.getLogger(__name__)

VERSION_RE = re.compile(r"^(?P<series>\d+\.\d+)\.(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
MANIFEST_VERSION_RE = re.compile(r"(?P<pre>[\"']version[\"']\s*:\s*[\"'])(?P<version>[\d\.]+)(?P<post>[\"'])")
MANIFEST_NAME = "__manifest__.py"


def _bump_version(version):
    """Bump the minor version number."""
    mo = VERSION_RE.match(version)
    if not mo:
        raise Exception(f"Cannot bump version for invalid version string: {version}")

    series = mo.group("series")
    major = mo.group("major")
    minor = int(mo.group("minor")) + 1
    patch = 0

    return f"{series}.{major}.{minor}.{patch}"


def _get_manifest_path(addon_dir):
    """Get the manifest file path for an addon directory."""
    manifest_path = os.path.join(addon_dir, MANIFEST_NAME)
    if os.path.exists(manifest_path):
        return manifest_path
    return None


class PullRequests(models.Model):
    _inherit = "runbot_merge.pull_requests"

    bump_policy = fields.Selection(
        [
            ("bump", "bump"),
            ("nobump", "nobump"),
        ],
        tracking=True,
    )
    bump_modules = fields.Char(
        help="Comma-separated list of specific modules to bump. If empty, all modified modules are bumped.",
        tracking=True,
    )
    bump_warned = fields.Boolean(default=False)
    bump_status = fields.Selection(
        [
            ("success", "Bump Success"),
            ("failed", "Bump Failed"),
        ],
        tracking=True,
        help="Status of the version bump operation after merge",
    )

    def _parse_commands(self, author, comment, login):
        comment = dict(comment or {})
        body = comment.get("body") or ""

        project = self.repository.project_id
        bump_setting = None
        bump_modules = None
        bump_done = False

        for line in project._find_commands(body):
            if re.search(r"\bnobump\b", line, flags=re.IGNORECASE):
                bump_setting = "nobump"
            elif match := re.search(r"\bbump=([\w,]+)", line, flags=re.IGNORECASE):
                bump_setting = "bump"
                bump_modules = match.group(1)
            elif re.search(r"\bbump\b", line, flags=re.IGNORECASE):
                bump_setting = "bump"
            elif re.search(r"\bbumped\b", line, flags=re.IGNORECASE):
                bump_done = True

        if bump_setting:
            # Validate specific modules if provided
            if bump_modules:
                requested_module_names = [m.strip() for m in bump_modules.split(",")]
                modified_module_names = self._get_modified_modules_names()
                invalid_module_names = [m for m in requested_module_names if m not in modified_module_names]

                if invalid_module_names:
                    if self.bump_policy or self.bump_modules:
                        self.bump_policy = False
                        self.bump_modules = False
                    invalid_list = ", ".join(invalid_module_names)
                    self.env.ref("runbot_merge_ux.command.bump_invalid_modules")._send(
                        repository=self.repository,
                        pull_request=self.number,
                        format_args={"pr": self, "invalid_modules": invalid_list},
                    )
                    body = re.sub(r"\bbump(=[\w,]+)?\b", "", body, flags=re.IGNORECASE)
                    body = re.sub(r"\bnobump\b", "", body, flags=re.IGNORECASE)
                    comment["body"] = body
                    return super()._parse_commands(author, comment, login)

            if self.bump_policy != bump_setting or self.bump_modules != bump_modules:
                self.bump_policy = bump_setting
                self.bump_modules = bump_modules
                # Reset warning flag when bump policy is set
                self.bump_warned = False
                # if the bump policy is the only thing preventing (but not
                # *blocking*) staging, trigger a staging
                if self.state == "ready":
                    self.env.ref("runbot_merge.staging_cron")._trigger()
            # strip the tokens so the base parser does not reject them
            body = re.sub(r"\bbump(=[\w,]+)?\b", "", body, flags=re.IGNORECASE)
            body = re.sub(r"\bnobump\b", "", body, flags=re.IGNORECASE)
            comment["body"] = body

        if bump_done:
            if self.bump_status != "success" and self.bump_policy == "bump":
                self.bump_status = "success"
            # strip the token so the base parser does not reject it
            body = re.sub(r"\bbumped\b", "", body, flags=re.IGNORECASE)
            comment["body"] = body

        return super()._parse_commands(author, comment, login)

    def _get_modified_modules_names(self):
        """Get the set of module names modified in this PR using GitHub API."""
        self.ensure_one()
        try:
            github_api = self.repository.github()
            files_response = github_api("get", f"pulls/{self.number}/files")
            files = files_response.json() if files_response else []

            modified_module_names = set()
            for file_info in files:
                filename = file_info.get("filename", "")
                # Get the top-level folder from the file path
                if "/" in filename:
                    modified_module_names.add(filename.split("/")[0])
            return modified_module_names
        except Exception as e:
            _logger.warning("Could not get modified modules for PR %s: %s", self.number, e)
            return set()

    def action_retry_version_bump(self):
        """Retry version bump for failed PRs."""
        self.ensure_one()
        if self.bump_status != "failed":
            return

        try:
            github_api = self.repository.github()
            self._bump_versions_in_repository(self.repository, github_api)
            self.bump_status = "success"
            self.env.ref("runbot_merge_ux.command.version_bump_success")._send(
                repository=self.repository,
                pull_request=self.number,
                format_args={"pr": self},
            )
        except Exception as e:
            error_msg = str(e)
            self.message_post(body=f"Version bump retry failed: {error_msg}")

    def _notify_provider_version_bump_failure(self, error_message):
        """Notify the SaaS provider about version bump failures."""
        try:
            provider_url = self.env["ir.config_parameter"].sudo().get_param("saas_client.provider_url")
            provider_token = self.env["ir.config_parameter"].sudo().get_param("saas_provider.odoo_project_token")

            if not provider_url:
                _logger.warning("No provider_url configured, cannot notify version bump failure")
                return

            if not provider_token:
                _logger.warning("No saas_provider.odoo_project_token configured, cannot notify version bump failure")
                return

            url = f"{provider_url}/runbot_merge/version_bump_failure"
            headers = {
                "content-type": "application/json",
                "token": provider_token,
            }

            # Prepare data for each PR
            pr_data = []
            for pr in self:
                pr_data.append(
                    {
                        "url": pr.github_url,
                        "author": f"{pr.author.name} ({pr.author.github_login})" if pr.author else "Unknown",
                        "reviewer": f"{pr.reviewed_by.name} ({pr.reviewed_by.github_login})"
                        if pr.reviewed_by
                        else "Unknown",
                        "error": error_message,
                    }
                )

            params = {
                "failures": pr_data,
            }

            data = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": params,
            }

            res = requests.post(
                url,
                data=json.dumps(data),
                headers=headers,
                timeout=30,
            )

            if res.status_code != 200:
                _logger.error("Error notifying provider: %s", res.status_code)
                return
            result = res.json().get("result")
            if result and result.get("error"):
                _logger.error("Error notifying provider: %s", result.get("error"))
            else:
                _logger.info("Successfully notified provider about version bump failures")

        except Exception as e:
            _logger.error("Failed to notify provider about version bump failure: %s", e, exc_info=True)

    def _bump_versions_in_repository(self, repository, github_api):
        """Bump versions in a specific repository."""
        if not self:
            return

        target_branch = self[0].target.name

        # Create a temporary directory for our work
        tmpdir = tempfile.mkdtemp(prefix="version_bump_")
        try:
            # Get the bare repository and clone it
            bare_repo = git.get_local(repository)
            if not bare_repo:
                _logger.warning("Could not get repository %s", repository.name)
                return

            # Get the current remote HEAD (which should include the just-merged commits)
            current_remote_head = github_api.head(target_branch)

            # Clone from the current remote head (after the merge)
            repo = bare_repo.clone(tmpdir)

            # Fetch the specific commit from GitHub to ensure we have it
            repo.with_config(check=True)._run("fetch", git.source_url(repository), current_remote_head)

            # Checkout the specific commit that includes the merge
            repo.with_config(check=True)._run("checkout", current_remote_head)

            # Find and bump versions
            manifest_updates = {}
            bumped_info = {}  # addon_name -> new_version

            # Get list of specific modules to bump if specified
            if self and self[0].bump_modules:
                specific_module_names = [m.strip() for m in self[0].bump_modules.split(",")]
                addons_to_bump = []
                for module_name in specific_module_names:
                    addon_path = os.path.join(tmpdir, module_name)
                    if os.path.exists(os.path.join(addon_path, MANIFEST_NAME)):
                        addons_to_bump.append(addon_path)
            else:
                addons_to_bump = self._get_modified_addons_for_prs(repo, tmpdir)

            for addon_dir in addons_to_bump:
                addon_name = os.path.basename(addon_dir)
                manifest_path = _get_manifest_path(addon_dir)
                if not manifest_path:
                    _logger.warning("No manifest found in addon directory %s", addon_dir)
                    continue

                try:
                    with open(manifest_path, "rb") as f:
                        manifest = ast.literal_eval(f.read().decode("utf-8"))

                    current_version = manifest.get("version")
                    if not current_version:
                        continue

                    new_version = _bump_version(current_version)
                    if new_version == current_version:
                        continue

                    if self._set_manifest_version(addon_dir, new_version):
                        addon_name = os.path.basename(addon_dir)
                        bumped_info[addon_name] = new_version
                        _logger.info("Bumping %s from %s to %s", addon_name, current_version, new_version)

                        # Read the updated manifest content and store for tree update
                        with open(manifest_path) as f:
                            updated_content = f.read()
                        rel_path = os.path.relpath(manifest_path, tmpdir)
                        manifest_updates[rel_path] = lambda repo, path, content=updated_content: content.encode()

                except Exception as e:
                    raise Exception(f"Failed to process addon in {addon_dir}") from e

            if manifest_updates:
                # Git tree workflow: current tree → new tree → new commit → push
                current_tree = repo.get_tree("HEAD")
                new_tree = repo.update_tree(current_tree, manifest_updates)

                # Build commit message with bumped versions and merged PRs
                pr_list = ", ".join(pr.display_name for pr in self)
                addon_list = ", ".join(f"{name} {version}" for name, version in bumped_info.items())
                commit_msg = f"[BOT] Bump version: {addon_list}\n\nMerged: {pr_list}"

                # Create new commit pointing to updated tree
                current_head = repo.stdout().with_config(text=True, check=True).rev_parse("HEAD").stdout.strip()
                project = repository.project_id
                commit_result = repo.commit_tree(
                    tree=new_tree,
                    parents=[current_head],
                    message=commit_msg,
                    author=(project.github_name or "Mergebot", project.github_email or "mergebot@odoo.com"),
                    committer=(project.github_name or "Mergebot", project.github_email or "mergebot@odoo.com"),
                )
                if commit_result.returncode:
                    raise Exception(f"Failed to create version bump commit: {commit_result.stderr}")
                new_commit = commit_result.stdout.strip()

                # Update HEAD to point to new commit, then push
                repo.with_config(check=True).update_ref("HEAD", new_commit)
                push_result = repo.push(git.source_url(repository), f"HEAD:refs/heads/{target_branch}")
                if push_result.returncode:
                    raise Exception(f"Failed to push version bump: {push_result.stderr}")

                _logger.info(
                    "Successfully pushed version bump to %s@%s: %s", repository.name, target_branch, new_commit
                )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _get_modified_addons_for_prs(self, repo, repo_path):
        """Get list of addon paths that were modified by the given PRs."""
        modified_addons = set()
        for pr in self:
            # Fetch the PR branch and its target base from GitHub
            fetch_pr = repo.with_config(check=True)._run(
                "fetch", git.source_url(pr.repository), f"pull/{pr.number}/head:pr-{pr.number}"
            )
            if fetch_pr.returncode != 0:
                raise Exception(f"Could not fetch PR {pr.number}: {fetch_pr.stderr}")
            fetch_target = repo.with_config(check=True)._run(
                "fetch", git.source_url(pr.repository), f"{pr.target.name}:target-{pr.target.name}"
            )
            if fetch_target.returncode != 0:
                raise Exception(f"Could not fetch target branch {pr.target.name}: {fetch_target.stderr}")

            # Get modified files using diff against the merge-base
            # This ensures we only see changes from this PR, not from other merged PRs
            diff_result = (
                repo.stdout()
                .with_config(text=True, check=True)
                .diff("--name-only", f"target-{pr.target.name}...pr-{pr.number}")
            )
            if diff_result.returncode != 0:
                raise Exception(f"Could not get diff for PR {pr.number}: {diff_result.stderr}")
            modified_folders = set(
                line.split("/")[0] for line in diff_result.stdout.strip().split("\n") if line.strip()
            )
            for folder in modified_folders:
                addon_path = os.path.join(repo_path, folder)
                if os.path.exists(os.path.join(addon_path, MANIFEST_NAME)):
                    modified_addons.add(addon_path)

        return list(modified_addons)

    def _set_manifest_version(self, addon_dir, version):
        """Set the version in the manifest file."""
        manifest_path = _get_manifest_path(addon_dir)
        if not manifest_path:
            raise Exception(f"No manifest file found in {addon_dir}")

        try:
            with open(manifest_path) as f:
                manifest_content = f.read()

            new_manifest = MANIFEST_VERSION_RE.sub(r"\g<pre>" + version + r"\g<post>", manifest_content)

            with open(manifest_path, "w") as f:
                f.write(new_manifest)

            return True
        except Exception as e:
            raise Exception(f"Failed to set version in {manifest_path}") from e
