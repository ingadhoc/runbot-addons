import fnmatch
import os

from odoo import models
from odoo.tools import config


class RunbotBuild(models.Model):
    _inherit = "runbot.build"

    def _get_addons_path(self):
        """parche de metodo nativo para que si el path no es valido no lo pase como addons path porque odoo no levanta
        esto es practico para nuevas versiones donde todavia no hay modulos carpetas dentro (caso oca que se inicializan vacios)"""
        for commit in self.env.context.get("defined_commit_ids") or self.params_id.commit_ids:
            if not commit.repo_id.manifest_files:
                continue  # skip repo without addons
            source_path = self._docker_source_folder(commit)
            for addons_path in (commit.repo_id.addons_paths or "").split(","):
                if os.path.isdir(commit._source_path(addons_path)) and config._is_addons_path(
                    commit._source_path(addons_path)
                ):
                    yield os.path.join(source_path, addons_path).strip(os.sep)

    def _get_test_tags_from_modules(self):
        """Return a list of --test-tags values derived from test_modules patterns defined
        on the trigger's repos (repo_ids + dependency_ids).

        Mirrors the semantics of the native 'modules' field on runbot.repo:
          - empty          → all modules of that repo
          - positive pat   → adds matching modules to the (already full) set
          - negative pat   → removes matching modules from the set
          - '-*,sale'      → empties first, then adds sale (idiomatic way to select a subset)

        To disable injection entirely, unset 'test_enable' on the config step.

        Returns:
            []             if all patterns resolved to an empty module set (no injection)
            ['/mod', ...]  list of per-module tag strings ready to inject into --test-tags
        """
        self.ensure_one()
        available_modules = self._get_available_modules()

        def _filter_patterns(patterns_list, default, all_modules):
            """Identical to the native _filter_patterns inside _filter_modules_to_test."""
            current = set(default)
            for pat in patterns_list:
                pat = pat.strip()
                if not pat:
                    continue
                if pat.startswith("-"):
                    pat = pat.strip("- ")
                    current -= {mod for mod in current if fnmatch.fnmatch(mod, pat)}
                else:
                    current |= {mod for mod in all_modules if fnmatch.fnmatch(mod, pat)}
            return current

        modules_to_test = set()
        for repo, repo_available_modules in available_modules.items():
            repo_modules = set(repo_available_modules)
            if repo.test_modules:
                repo_modules = _filter_patterns(
                    repo.test_modules.split(","),
                    repo_modules,
                    repo_available_modules,
                )
            modules_to_test |= repo_modules

        return ["/" + module for module in sorted(modules_to_test)]
