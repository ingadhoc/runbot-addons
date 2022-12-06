{
    'name': "runbot",
    'summary': "Runbot",
    'description': "Runbot for Odoo 15.0",
    'author': "ADHOC SA",
    'website': "http://runbot.odoo.com",
    'category': 'Website',
    'version': "15.0.1.0.0",
    'depends': ['runbot'],
    'data': [
        'views/runbot_project_views.xml',
        'views/runbot_repo_views.xml',
        'views/runbot_trigger_views.xml',
    ],
}
