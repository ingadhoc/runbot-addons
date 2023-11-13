import os
from odoo import models
from odoo.tools import config
from odoo.tools.safe_eval import safe_eval


class RunbotBuild(models.Model):
    _inherit = 'runbot.build'

    def _cmd(self, python_params=None, py_version=None, local_only=True, sub_command=None, enable_log_db=True):

        command = super()._cmd(
            python_params=python_params, py_version=py_version, local_only=local_only, sub_command=sub_command, enable_log_db=enable_log_db)
        if self.version_id.custom_pre_commands:
            command.pres += safe_eval(self.version_id.custom_pre_commands)
        return command

    def _get_addons_path(self):
        """ parche de metodo nativo para que si el path no es valido no lo pase como addons path porque odoo no levanta
        esto es practico para nuevas versiones donde todavia no hay modulos carpetas dentro (caso oca que se inicializan vacios)"""
        for commit in (self.env.context.get('defined_commit_ids') or self.params_id.commit_ids):
            if not commit.repo_id.manifest_files:
                continue  # skip repo without addons
            source_path = self._docker_source_folder(commit)
            for addons_path in (commit.repo_id.addons_paths or '').split(','):
                if os.path.isdir(commit._source_path(addons_path)) and config._is_addons_path(commit._source_path(addons_path)):
                    yield os.path.join(source_path, addons_path).strip(os.sep)
