from odoo import models


class RunbotBuildConfigStep(models.Model):
    _inherit = "runbot.build.config.step"

    def _run_install_odoo(self, build, config_data=None):
        res = super()._run_install_odoo(build, config_data=config_data)
        # Same merge as the base method: build params win over the caller's data.
        config_data = {**(config_data or {}), **build.params_id.config_data}
        if not res or not res.get("cmd") or not config_data.get("test_enable", self.test_enable):
            return res

        dynamic_tags = build._get_test_tags_from_modules()
        if not dynamic_tags:
            return res

        cmd = res["cmd"]
        # Dynamic module tags go first; any tags already set by the config step
        # (self.test_tags) act as a final filter applied on top.
        if "--test-tags" in cmd.cmd:
            idx = cmd.cmd.index("--test-tags")
            cmd.cmd[idx + 1] = ",".join(dynamic_tags) + "," + cmd.cmd[idx + 1]
        elif "--test-enable" in cmd.cmd:
            cmd.extend(["--test-tags", ",".join(dynamic_tags)])
        else:
            build._log(
                "_run_install_odoo",
                "runbot_ux: --test-enable not found in cmd, dynamic test tags not injected (%s)"
                % ",".join(dynamic_tags),
                level="WARNING",
            )
            return res

        build._log(
            "_run_install_odoo",
            "runbot_ux: injected dynamic test tags: %s" % ",".join(dynamic_tags),
        )
        return res
