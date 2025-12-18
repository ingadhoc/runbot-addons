{
    "name": "Runbot Weblate",
    "summary": "Runbot Weblate Integration",
    "author": "ADHOC SA",
    "website": "http://runbot.odoo.com",
    "category": "Website",
    "version": "18.0.1.0.0",
    "depends": ["runbot"],
    "data": [
        "security/ir.model.access.csv",
        "views/runbot_branch_views.xml",
        "views/weblate_project_views.xml",
    ],
    "external_dependencies": {
        "python": ["github"],
    },
    "license": "AGPL-3",
    "installable": False,
}
