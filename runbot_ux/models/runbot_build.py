import configparser
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

        A build with config_data['disable_module_tags'] gets nothing injected
        and runs only the tags it carries. That is how each child of a fan-out
        runs its part, and it mirrors the native 'disable_auto_tags' key.

        To disable injection entirely, unset 'test_enable' on the config step.

        Returns:
            []             if all patterns resolved to an empty module set (no injection)
            ['/mod', ...]  list of per-module tag strings ready to inject into --test-tags
        """
        self.ensure_one()
        if self.params_id.config_data.get("disable_module_tags"):
            return []

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

    def _create_post_install_children(self, number_builds):
        """Split the post_install tests of this build into `number_builds` children.

        `number_builds` is the field of the step, set from the interface: it is
        not declared with the step, because it is a number to tune.

        Every child restores the database this build dumped and runs a part of
        the modules, so the tests of one commit run at the same time. The
        negative tags go to every child: they turn tests off and have to keep
        them off everywhere.
        """
        self.ensure_one()
        if number_builds <= 1:
            self._log(
                "create_build",
                "number_builds is not set on this step, so every test goes to a single child",
                level="WARNING",
            )
        child_config = self.env.ref("runbot_ux.build_config_test_post_install")
        # The children take the database and the tags from the last install step.
        install_step = self.params_id.config_id.step_ids.filtered(lambda step: step.job_type == "install_odoo")[-1:]
        # The parent skips post_install so the children can run it.
        tags = [
            tag
            for raw in (install_step.test_tags or "").split(",")
            if (tag := raw.strip()) and tag.lstrip("-+") != "post_install"
        ]
        excluded = [tag for tag in tags if tag.startswith("-")]
        to_split = self._get_test_tags_from_modules() + [tag for tag in tags if not tag.startswith("-")]
        for part in self._split_test_tags(to_split, number_builds):
            child = self._add_child(
                {
                    "config_id": child_config.id,
                    # The keys of the parent come along, because the child has to
                    # behave like it: skip_requirements is one of them, and
                    # without it the child pip installs from git with no network.
                    "config_data": {
                        **self.params_id.config_data,
                        # The install step leaves a zip of its database next to its logs.
                        "dump_url": "%s%s-%s.zip" % (self._http_log_url(), self.dest, install_step.db_name),
                        # With nothing to update odoo runs every at_install
                        # test, and the parent already ran them.
                        "test_tags": ",".join(part + excluded + ["-at_install"]),
                        "disable_module_tags": True,
                    },
                },
                description="post install tests for **%s -> %s**" % (part[0].lstrip("/"), part[-1].lstrip("/")),
            )
            self._log(
                "create_build", "created with config %s" % child_config.name, log_type="subbuild", path=str(child.id)
            )

    def _split_test_tags(self, tags, count):
        """Cut the sorted tags into at most `count` ranges of a similar weight.

        Sorted, so a part can be named by its bounds, the way odoo does it.
        Weights are seconds per module from runbot.build.stat, which make_stats
        fills with the test_time regex. A row holds only what that build ran,
        so several are read; they are rough, because a module tested next to
        seven others is slower than one tested alone. A tag never measured
        counts as one second.
        """
        times = {}
        # 50 rows is a handful of builds, because a fan-out leaves one row per
        # child and each of them holds a part of the modules.
        stats = self.env["runbot.build.stat"].search(
            [
                ("category", "=", "test_time"),
                ("build_id.params_id.trigger_id", "=", self.params_id.trigger_id.id),
            ],
            order="id desc",
            limit=50,
        )
        for stat in stats:
            for module, seconds in stat.values.items():
                times.setdefault(module, seconds)  # the newest build wins

        def weight(tag):
            return times.get(tag.lstrip("/"), 1)

        tags = sorted(tags)

        def parts_under(limit):
            """The ranges that come out when none of them may pass `limit`."""
            parts, part, load = [], [], 0
            for tag in tags:
                if part and load + weight(tag) > limit:
                    parts.append(part)
                    part, load = [], 0
                part.append(tag)
                load += weight(tag)
            if part:
                parts.append(part)
            return parts

        # Look for the lightest limit that still fits in `count` ranges, so no
        # range is heavier than a range split can make it. Cutting at the
        # average instead leaves everything that is left in the last range.
        low, high = max(map(weight, tags), default=0), sum(map(weight, tags))
        while high - low > 0.01:
            middle = (low + high) / 2
            if len(parts_under(middle)) <= count:
                high = middle
            else:
                low = middle
        return parts_under(high)

    def _docker_run(self, *args, **kwargs):
        res = super()._docker_run(*args, **kwargs)
        # The base method has just written .odoorc; inject the auto-install
        # policy so the build honors the same modules as client bases.
        self._inject_auto_install_config()
        return res

    def _inject_auto_install_config(self):
        """Write the version's auto-install lists into the build's .odoorc.

        Key names differ by version: 19.0+ uses the [module_change_auto_install]
        section, 18.0 and older use the flat [options] keys. Both are read by the
        saas_client patch.
        """
        self.ensure_one()
        version = self.params_id.version_id
        enabled = version.modules_auto_install_enabled or ""
        disabled = version.modules_auto_install_disabled or ""
        if not enabled and not disabled:
            return  # nothing to inject (e.g. master, which has no policy)

        if version.name >= "19.0":
            section, key_enabled, key_disabled = "module_change_auto_install", "modules_enabled", "modules_disabled"
        else:
            section, key_enabled, key_disabled = (
                "options",
                "modules_auto_install_enabled",
                "modules_auto_install_disabled",
            )

        rc_path = self._path(".odoorc")
        if not os.path.exists(rc_path):
            return
        # RawConfigParser: no %-interpolation, so existing values (e.g. log
        # formats) with '%' don't blow up on read.
        parser = configparser.RawConfigParser()
        parser.read(rc_path)
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key_enabled, enabled)
        parser.set(section, key_disabled, disabled)
        with open(rc_path, "w") as rc_file:
            parser.write(rc_file)
