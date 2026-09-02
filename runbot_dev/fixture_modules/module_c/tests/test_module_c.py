import time

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestModuleC(TransactionCase):
    """Fixture for the runbot fan-out probe: a known, measurable duration."""

    def test_takes_3s(self):
        time.sleep(3)
        self.assertTrue(self.env["res.users"].search([], limit=1))
