{
    "name": "Runbot Attach VS Code",
    "summary": "Attach a code-server VS Code session to a wakeable runbot build",
    "author": "ADHOC SA",
    "website": "https://www.adhoc.com.ar",
    "category": "Website",
    "version": "18.0.2.0.0",
    "depends": ["runbot"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "data/runbot_docker_layer.xml",
        "data/ir_cron_data.xml",
        "views/runbot_build_views.xml",
        "views/runbot_frontend_templates.xml",
        "views/runbot_nginx.xml",
    ],
    "demo": [
        "demo/runbot_attach_vscode_demo.xml",
    ],
    "license": "AGPL-3",
    "installable": True,
}
