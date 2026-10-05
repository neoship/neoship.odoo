import json

import psycopg2
import requests

from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import (
    PROD_TRACKING_URL,
    PROD_URL,
    TEST_TRACKING_URL,
    TEST_URL,
)

from .common import NeoshipCommon, make_response, mock_neoship


@tagged('post_install', '-at_install')
class TestDeliveryCarrier(NeoshipCommon):
    def test_form_saves_without_delivery_product(self):
        with Form(self.env['delivery.carrier']) as carrier_form:
            carrier_form.name = 'Neoship SPS'
            carrier_form.delivery_type = const.DELIVERY_TYPE
            carrier_form.neoship_username = 'user@example.com'
            carrier_form.neoship_password = 'secret-password'
            carrier_form.fixed_price = 3.9
        carrier = carrier_form.record
        self.assertEqual(carrier.product_id.name, 'Neoship SPS')
        self.assertEqual(carrier.product_id.type, const.ODOO_PRODUCT_TYPE_SERVICE)
        self.assertEqual(carrier.product_id.list_price, 3.9)

    def test_each_carrier_gets_its_own_product(self):
        carriers = self.env['delivery.carrier'].create(
            [
                {'name': 'Neoship GLS', 'delivery_type': const.DELIVERY_TYPE},
                {'name': 'Neoship Packeta', 'delivery_type': const.DELIVERY_TYPE},
            ]
        )
        self.assertEqual(len(carriers.product_id), 2)

    def test_existing_product_is_kept(self):
        self.assertEqual(self.carrier.product_id, self.delivery_product)

    def test_connection_uses_test_environment_by_default(self):
        with mock_neoship(make_response(json_data={'token': 't'})) as calls:
            action = self.carrier.action_neoship_test_connection()
        self.assertEqual(calls[-1]['url'], TEST_URL + '/login_check')
        self.assertEqual(action['params']['type'], 'success')

    def test_connection_uses_production_environment(self):
        self.carrier.prod_environment = True
        with mock_neoship(make_response(json_data={'token': 't'})) as calls:
            self.carrier.action_neoship_test_connection()
        self.assertEqual(calls[-1]['url'], PROD_URL + '/login_check')

    def test_connection_failure_does_not_leak_password(self):
        with (
            mock_neoship(make_response(401, {'message': 'Invalid credentials'})),
            self.assertRaisesRegex(UserError, 'Invalid credentials') as error,
        ):
            self.carrier.action_neoship_test_connection()
        self.assertNotIn('secret-password', str(error.exception))

    def test_connection_timeout_is_reported_without_details(self):
        with (
            mock_neoship(requests.exceptions.ReadTimeout()),
            self.assertRaisesRegex(UserError, 'did not respond in time') as error,
        ):
            self.carrier.action_neoship_test_connection()
        self.assertNotIn('login_check', str(error.exception))

    def test_connection_requires_credentials(self):
        self.carrier.neoship_password = False
        with self.assertRaisesRegex(UserError, 'username and password'):
            self.carrier.action_neoship_test_connection()

    def test_cod_domain(self):
        partner = self.env['res.partner'].create({'name': 'COD Customer'})
        other_partner = self.env['res.partner'].create({'name': 'Prepaid Customer'})
        cod_order = self.env['sale.order'].create({'partner_id': partner.id})
        prepaid_order = self.env['sale.order'].create({'partner_id': other_partner.id})

        self.assertFalse(self.carrier._neoship_is_cod(cod_order))

        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {partner.id})]"
        self.assertTrue(self.carrier._neoship_is_cod(cod_order))
        self.assertFalse(self.carrier._neoship_is_cod(prepaid_order))

    def test_send_shipping_is_not_implemented(self):
        with self.assertRaises(UserError):
            self.carrier.send_shipping(self.env['stock.picking'])

    def _picking(self, tracking_ref):
        return self.env['stock.picking'].new({'carrier_id': self.carrier.id, 'carrier_tracking_ref': tracking_ref})

    def test_tracking_link_uses_test_environment(self):
        link = self.carrier.get_tracking_link(self._picking('202605101419'))
        self.assertEqual(link, TEST_TRACKING_URL + '202605101419/')

    def test_tracking_link_uses_production_environment(self):
        self.carrier.prod_environment = True
        link = self.carrier.get_tracking_link(self._picking('202605101419'))
        self.assertEqual(link, 'https://aplikacia.neoship.sk/tracking/202605101419/')
        self.assertTrue(link.startswith(PROD_TRACKING_URL))

    def test_tracking_link_for_multiple_numbers(self):
        links = json.loads(self.carrier.get_tracking_link(self._picking('111, 222')))
        self.assertEqual(links, [['111', TEST_TRACKING_URL + '111/'], ['222', TEST_TRACKING_URL + '222/']])

    def test_tracking_link_without_tracking_number(self):
        self.assertFalse(self.carrier.get_tracking_link(self._picking(False)))

    def test_default_weight_cannot_be_negative(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.errors.CheckViolation):
            self.carrier.neoship_default_weight = -1
            self.carrier.flush_recordset()
