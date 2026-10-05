from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.delivery_neoship.models.neoship_api import PROD_URL, TEST_URL

from .common import NeoshipCommon, make_response, mock_neoship


@tagged('post_install', '-at_install')
class TestDeliveryCarrier(NeoshipCommon):

    def test_connection_uses_test_environment_by_default(self):
        with mock_neoship(make_response(json_data={'token': 't'})) as mock_request:
            action = self.carrier.action_neoship_test_connection()
        self.assertEqual(mock_request.call_args.args[1], TEST_URL + '/login_check')
        self.assertEqual(action['params']['type'], 'success')

    def test_connection_uses_production_environment(self):
        self.carrier.prod_environment = True
        with mock_neoship(make_response(json_data={'token': 't'})) as mock_request:
            self.carrier.action_neoship_test_connection()
        self.assertEqual(mock_request.call_args.args[1], PROD_URL + '/login_check')

    def test_connection_failure_does_not_leak_password(self):
        with mock_neoship(make_response(401, {'message': 'Invalid credentials'})):
            with self.assertRaisesRegex(UserError, 'Invalid credentials') as error:
                self.carrier.action_neoship_test_connection()
        self.assertNotIn('secret-password', str(error.exception))

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
