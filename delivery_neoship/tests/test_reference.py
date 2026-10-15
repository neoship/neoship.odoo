import re

from odoo.tests import BaseCase, tagged

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.tools import neoship_parcel_reference, neoship_reference

VALID = re.compile(r'^[A-Za-z0-9_-]+$')


@tagged('post_install', '-at_install')
class TestReference(BaseCase):
    def test_short_name_is_kept(self):
        self.assertEqual(neoship_reference('', 'S00221', 1), 'S00221-01')
        self.assertEqual(neoship_reference('C1-', 'S00221', 12), 'C1-S00221-12')
        self.assertEqual(neoship_reference('', 'WH/OUT/00012', 1), 'WH-OUT-00012-01')

    def test_long_names_ending_the_same_stay_unique(self):
        bratislava = neoship_reference('C1-', 'BRATISLAVA/CENTRAL-STORE/OUT/00001', 1)
        kosice = neoship_reference('C1-', 'KOSICE/CENTRAL-STORE/OUT/00001', 1)
        self.assertNotEqual(bratislava, kosice)
        self.assertEqual(bratislava[-12:], kosice[-12:])
        for reference in (bratislava, kosice):
            self.assertTrue(reference.startswith('C1-'))
            self.assertTrue(reference.endswith('-OUT-00001-01'))
            self.assertEqual(len(reference), const.REFERENCE_MAX_LENGTH - const.REFERENCE_PACK_ROOM)
            self.assertRegex(reference, VALID)

    def test_long_name_gives_the_same_reference_every_time(self):
        self.assertEqual(neoship_reference('', 'E2E/VERY-LONG-PREFIX-XYZ/00227', 2), 'YO1S-EFIX-XYZ-00227-02')

    def test_packeta_pack_suffix_fits(self):
        reference = neoship_reference('C12-', 'SHOP-2026-ORDER-0000123456', 99)
        self.assertLessEqual(len(neoship_parcel_reference(reference, 99)), const.REFERENCE_MAX_LENGTH)
        self.assertEqual(neoship_parcel_reference('S00221-01', 2), 'S00221-01_2')
        self.assertEqual(neoship_parcel_reference('S00221-01', 1), 'S00221-01')

    def test_package_copies_never_match_a_reference(self):
        references = {neoship_reference('', f'S{number:05d}', 1) for number in (10000, 100001)}
        copies = {f'{reference}{copy}' for reference in references for copy in range(1, 10)}
        self.assertFalse(references & copies)
        self.assertNotIn(f'{neoship_reference("", "S00221", 2)}1', {neoship_reference('', 'S00221', 21)})
