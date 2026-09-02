import time

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestModuleB(TransactionCase):
    """Fixture for the runbot fan-out probe: a known, measurable duration."""

    def test_takes_6s(self):
        time.sleep(6)
        self.assertTrue(self.env["res.users"].search([], limit=1))
