# -*- coding: utf-8 -*-
{
    'name': "Tunbot Transifex",
    'summary': "Runbot Transifex",
    'description': "Runbot for Odoo 13.0",
    'author': "ADHOC SA",
    'website': "http://runbot.odoo.com",
    'category': 'Website',
    'version': '13.0.1.1.0',
    'depends': ['runbot'],
    'data': [
        'views/transifex_project_views.xml',
        'views/runbot_branch_views.xml',
        'data/runbot_build_config_data.xml',
        'data/ir_cron_data.xml',
        'security/ir.model.access.csv',
    ],
    'demo': [
        'demo/runbot_pupulate_demo.xml',
        'demo/runbot_transifex_demo.xml',
    ],
}
