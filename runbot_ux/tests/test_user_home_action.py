from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("-at_install", "post_install")
class TestUserHomeAction(TransactionCase):
    def test_new_user_has_no_home_action(self):
        user = new_test_user(self.env, login="runbot_home_action_user", groups="base.group_user")
        self.assertFalse(user.action_id)
