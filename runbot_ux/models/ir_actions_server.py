from odoo import models, api
import requests
import json


class IrActionsServer(models.Model):

    _inherit = 'ir.actions.server'

    @api.model
    def _get_eval_context(self, action=None):
        """ Enable re python library to json search and requests function from odoo tools """
        eval_context = super()._get_eval_context(action=action)
        eval_context.update({
            'json': json,
            'requests': requests,
        })
        return eval_context
