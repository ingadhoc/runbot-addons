{
    "name": "Runbot OpenCode",
    "summary": "Personal OpenCode workspace per user, always on the latest OBA sources",
    "author": "ADHOC SA",
    "website": "https://www.adhoc.com.ar",
    "category": "Website",
    "version": "18.0.1.0.0",
    # runbot_token_auth provides the shared signed-token auth (runbot.token.signer).
    "depends": ["runbot", "runbot_token_auth"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "data/ir_cron_data.xml",
        "views/runbot_opencode_workspace_views.xml",
        "views/runbot_opencode_bundle_views.xml",
        "views/runbot_frontend_templates.xml",
        "views/runbot_nginx.xml",
    ],
    "license": "AGPL-3",
    "installable": True,
}
