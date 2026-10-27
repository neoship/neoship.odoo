from odoo.tests import tagged

from odoo.addons.delivery_neoship import const

from .common import NeoshipCommon, login_ok, make_response, mock_neoship

INPOST_SIZES = [
    {'code': 'A', 'length': 64, 'width': 38, 'height': 8},
    {'code': 'B', 'length': 64, 'width': 38, 'height': 19},
    {'code': 'C', 'length': 64, 'width': 38, 'height': 41},
]
CARRIERS = [
    {
        'id': 3,
        'packeta_id': 131,
        'name': 'SK Packeta Home HD',
        'currency': 'EUR',
        'state': 'Slovensko',
        'state_code': 'SK',
        'available': True,
        'size_categories': [],
    },
    {
        'id': 7,
        'packeta_id': 3060,
        'name': 'PL InPost Paczkomaty Box',
        'currency': 'PLN',
        'state': 'Poľsko',
        'state_code': 'PL',
        'available': True,
        'size_categories': INPOST_SIZES,
    },
]


@tagged('post_install', '-at_install')
class TestPackageType(NeoshipCommon):
    def _load(self, carriers):
        with mock_neoship(login_ok(), make_response(json_data=carriers)):
            return self.carrier.action_neoship_load_package_types()

    def _package_types(self):
        return (
            self.env['stock.package.type']
            .search([('package_carrier_type', '=', const.DELIVERY_TYPE)])
            .sorted('shipper_package_code')
        )

    def test_packeta_sizes_are_loaded_as_package_types(self):
        action = self._load(CARRIERS)
        package_types = self._package_types()
        self.assertEqual(package_types.mapped('shipper_package_code'), ['A', 'B', 'C'])
        self.assertEqual(set(package_types.mapped('neoship_carrier_type')), {3060})
        self.assertEqual(package_types[0].name, 'PL InPost Paczkomaty Box A')
        self.assertIn('3 package types', action['params']['message'])

    def test_package_type_dimensions_are_in_the_length_unit_of_odoo(self):
        self._load(CARRIERS)
        package_type = self._package_types()[1]
        self.assertEqual(
            (package_type.packaging_length, package_type.width, package_type.height), (640.0, 380.0, 190.0)
        )

    def test_loading_again_updates_the_package_types(self):
        self._load(CARRIERS)
        loaded = self._package_types()
        resized = [{**INPOST_SIZES[0], 'height': 9}, *INPOST_SIZES[1:]]
        self._load([{**CARRIERS[1], 'size_categories': resized}])

        self.assertEqual(self._package_types(), loaded)
        self.assertEqual(loaded[0].height, 90.0)

    def test_loading_again_keeps_renamed_package_types(self):
        self._load(CARRIERS)
        package_type = self._package_types()[0]
        package_type.name = 'InPost small'
        self._load(CARRIERS)
        self.assertEqual(package_type.name, 'InPost small')

    def test_carrier_listed_twice_loads_its_sizes_once(self):
        action = self._load([*CARRIERS, {**CARRIERS[1], 'id': 8}])
        self.assertEqual(len(self._package_types()), 3)
        self.assertIn('3 package types', action['params']['message'])

    def test_package_types_made_by_users_are_kept(self):
        own = self.env['stock.package.type'].create(
            {'name': 'Our box', 'package_carrier_type': const.DELIVERY_TYPE, 'shipper_package_code': 'B'}
        )
        self._load(CARRIERS)
        self.assertEqual(own.name, 'Our box')
        self.assertEqual(len(self._package_types()), 4)

    def test_carriers_listed_without_sizes_load_nothing(self):
        carriers = [{key: value for key, value in carrier.items() if key != 'size_categories'} for carrier in CARRIERS]
        action = self._load(carriers)
        self.assertFalse(self._package_types())
        self.assertIn('0 package types', action['params']['message'])
