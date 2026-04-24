from odoo import models


class RunbotBuildConfigStep(models.Model):
    _inherit = "runbot.build.config.step"

    def _run_install_odoo(self, build):
        res = super()._run_install_odoo(build)
        if not res or not res.get("cmd"):
            return res

        if not self.test_enable:
            return res

        dynamic_tags = build._get_test_tags_from_modules()
        if not dynamic_tags:
            return res

        cmd = res["cmd"]
        # cmd.cmd is the underlying list of command arguments
        # Dynamic module tags go first; any tags already set by the config step
        # (self.test_tags) act as a final filter applied on top.
        if "--test-tags" in cmd.cmd:
            idx = cmd.cmd.index("--test-tags")
            cmd.cmd[idx + 1] = ",".join(dynamic_tags) + "," + cmd.cmd[idx + 1]
        elif "--test-enable" in cmd.cmd:
            cmd.extend(["--test-tags", ",".join(dynamic_tags)])

        return res
