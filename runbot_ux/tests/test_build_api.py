from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestBuildApi(HttpCase):
    def setUp(self):
        super().setUp()
        self.env["runbot.host"].create({"name": "b1.example.com"})
        project = self.env["runbot.project"].create({"name": "Tests"})
        params = self.env["runbot.build.params"].create(
            {
                "version_id": self.env["runbot.version"]._get("19.0").id,
                "project_id": project.id,
                "config_id": self.env.ref("runbot.runbot_build_config_default").id,
            }
        )
        Build = self.env["runbot.build"]
        self.parent = Build.create({"params_id": params.id, "host": "b1.example.com", "log_list": "base,all"})
        self.child = Build.create({"params_id": params.id, "parent_id": self.parent.id, "description": "account_ux"})

    def test_public_summary_lists_children_and_logs(self):
        response = self.url_open(f"/runbot/api/build/{self.parent.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"id", "description", "state", "result", "logs", "parent_id", "children"})
        self.assertEqual(data["parent_id"], None)
        self.assertEqual(
            data["logs"],
            [f"{self.parent._http_log_url()}base.txt", f"{self.parent._http_log_url()}all.txt"],
        )
        self.assertEqual(
            data["children"],
            [
                {
                    "id": self.child.id,
                    "description": "account_ux",
                    "state": self.child.global_state,
                    "result": self.child.global_result,
                    "logs": [],
                }
            ],
        )

    def test_unknown_build_is_not_found(self):
        response = self.url_open("/runbot/api/build/999999999")
        self.assertEqual(response.status_code, 404)
