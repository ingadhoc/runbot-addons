from odoo import models, fields
from odoo.tools.safe_eval import safe_eval


class RunbotBuild(models.Model):
    _inherit = 'runbot.build'

    def _cmd(self, python_params=None, py_version=None, local_only=True, sub_command=None):
        command = super()._cmd(
            python_params=python_params, py_version=py_version, local_only=local_only, sub_command=sub_command)
        if self.version_id.custom_pre_commands:
            command.pres += safe_eval(self.version_id.custom_pre_commands)
        return command
