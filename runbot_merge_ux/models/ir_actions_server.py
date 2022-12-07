from odoo import models, api
from odoo.tools.safe_eval import wrap_module
import requests


class IrActionsServer(models.Model):

    _inherit = 'ir.actions.server'

    @api.model
    def _get_eval_context(self, action=None):
        """ Enable re python library to json search and requests function from odoo tools """
        eval_context = super()._get_eval_context(action=action)
        eval_context.update({
            'requests': wrap_module(__import__('requests'), []),
        })
        return eval_context