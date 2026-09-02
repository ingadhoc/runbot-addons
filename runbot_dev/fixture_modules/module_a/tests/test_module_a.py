import time

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestModuleA(TransactionCase):
    """Fixture for the runbot fan-out probe: a known, measurable duration."""

    def test_takes_10s(self):
        time.sleep(10)
        self.assertTrue(self.env["res.users"].search([], limit=1))
