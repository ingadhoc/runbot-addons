from odoo.http import route, request
from odoo.addons.runbot_merge.controllers.dashboard import MergebotDashboard


class MergebotDashboard(MergebotDashboard):
    @route('/runbot_merge', auth="public", type="http", website=True, sitemap=True)
    def dashboard(self):
        # use different variable name to dont overlap with runbot projects that are used to render menu
        projects = request.env['runbot_merge.project'].with_context(active_test=False).sudo().search([])
        stagings = {
            branch: projects.env['runbot_merge.stagings'].search([
                ('target', '=', branch.id)], order='staged_at desc', limit=6)
            for project in projects
            for branch in project.branch_ids
            if branch.active
        }
        prefetch_set = list({
            id
            for stagings in stagings.values()
            for id in stagings.ids
        })
        for st in stagings.values():
            st._prefetch_ids = prefetch_set
        return request.render('runbot_merge.dashboard', {
            'runbot_merge_projects': projects,
            'stagings_map': stagings,
        })
