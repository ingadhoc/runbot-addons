{
    "name": "Runbot Attach VS Code",
    "summary": "Attach a code-server VS Code session to a wakeable runbot build",
    "author": "ADHOC SA",
    "website": "https://www.adhoc.com.ar",
    "category": "Website",
    "version": "18.0.1.1.0",
    "depends": ["runbot"],
    "data": [
        "data/ir_config_parameter.xml",
        "data/runbot_docker_layer.xml",
        "views/runbot_build_views.xml",
    ],
    "license": "AGPL-3",
    "installable": True,
}
