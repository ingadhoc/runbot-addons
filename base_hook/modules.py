from odoo.addons.base.models import ir_module
import os
import logging

_logger = logging.getLogger(__name__)


original_get_module_info = ir_module.Module.get_module_info


@classmethod
def new_get_module_info(cls, name):
    res = original_get_module_info(name)
    ignore_auto_install_modules = os.environ.get('ignore_auto_install_modules')
    if res and ignore_auto_install_modules and name in ignore_auto_install_modules.split(','):
        _logger.info('Ignoring auto installation of %s', name)
        res['auto_install'] = False
    return res


ir_module.Module.get_module_info = new_get_module_info
