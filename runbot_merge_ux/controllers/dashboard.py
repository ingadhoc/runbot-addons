from odoo.http import route, request
from odoo.addons.runbot_merge.controllers.dashboard import MergebotDashboard


class MergebotDashboard(MergebotDashboard):
    @route('/runbot_merge', auth="public", type="http", website=True)
    def dashboard(self):
        # use different variable name to dont overlap with runbot projects that are used to render menu
        return request.render('runbot_merge.dashboard', {
            'runbot_merge_projects': request.env['runbot_merge.project'].with_context(active_test=False).sudo().search([]),
        })
