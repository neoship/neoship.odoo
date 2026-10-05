import os
import unittest

from odoo.tests import BaseCase, tagged

from odoo.addons.delivery_neoship.models.neoship_api import TEST_URL, NeoshipClient


@tagged('-standard', 'neoship_live')
class TestNeoshipLive(BaseCase):
    def setUp(self):
        super().setUp()
        username = os.environ.get('NEOSHIP_USERNAME')
        password = os.environ.get('NEOSHIP_PASSWORD')
        if not username or not password:
            raise unittest.SkipTest('NEOSHIP_USERNAME and NEOSHIP_PASSWORD are not set')
        self.client = NeoshipClient(os.environ.get('NEOSHIP_API') or TEST_URL, username, password)
        self.addCleanup(self.client.close)

    def test_login(self):
        self.assertTrue(self.client.login())
