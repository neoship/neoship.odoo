from unittest.mock import patch

import requests
from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import LockError, UserError
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import PROD_URL, TEST_TRACKING_URL, TEST_URL

from .common import NeoshipCommon, make_response, mock_neoship

LOGIN_OK = {'token': 'token-1'}
PDF = b'%PDF-1.5 label'
NOT_FOUND = make_response(404, {})


def created(package_id=501, tracking_number='TRK1', reference='REF'):
    return make_response(
        json_data=[{'id': package_id, 'reference_number': reference, 'tracking_number': tracking_number}]
    )


def found(package_id=777, tracking_number='TRK-OLD', **values):
    shipment = {
        'id': package_id,
        'tracking_number': tracking_number,
        'receiver_name': 'Jan Testovaci',
        'receiver_street': 'Hlavna 1',
        'receiver_city': 'Kosice',
        'receiver_zip': '04001',
        'receiver_state_code': 'SK',
        'parcelshop': None,
        'cod_price': None,
        'cod_currency_code': None,
        **values,
    }
    return make_response(json_data=[shipment])


def label():
    return make_response(content=PDF, content_type='application/pdf')


@tagged('post_install', '-at_install')
class TestSendShipping(NeoshipCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.country_sk = cls.env.ref('base.sk')
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.partner_id.write(
            {
                'street': 'Mlynske nivy 5',
                'city': 'Bratislava',
                'zip': '82109',
                'country_id': cls.country_sk.id,
                'email': 'warehouse@example.com',
                'phone': '+421900111222',
            }
        )
        cls.customer = cls.env['res.partner'].create(
            {
                'name': 'Jan Testovaci',
                'street': 'Hlavna 1',
                'city': 'Kosice',
                'zip': '04001',
                'country_id': cls.country_sk.id,
                'email': 'jan@example.com',
                'phone': '+421900123456',
            }
        )
        cls.product = cls.env['product.product'].create({'name': 'Vitamin C', 'type': 'consu', 'weight': 0.4})
        cls.carrier.write({'neoship_shipper_id': 2, 'neoship_shipper_code': 'SPS', 'neoship_shipper_name': 'SPS'})
        cls.order = cls._create_order(cls.customer)

    @classmethod
    def _create_order(cls, partner):
        return cls.env['sale.order'].create(
            {
                'partner_id': partner.id,
                'order_line': [(0, 0, {'product_id': cls.product.id, 'product_uom_qty': 2, 'price_unit': 15.0})],
            }
        )

    def _picking(self, order=None, partner=None, quantity=2):
        order = order or self.order
        picking = self.env['stock.picking'].create(
            {
                'picking_type_id': self.warehouse.out_type_id.id,
                'partner_id': (partner or order.partner_id).id,
                'carrier_id': self.carrier.id,
                'move_ids': [
                    (
                        0,
                        0,
                        {
                            'product_id': self.product.id,
                            'product_uom_qty': quantity,
                            'location_id': self.warehouse.lot_stock_id.id,
                            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
                        },
                    )
                ],
            }
        )
        picking.sale_id = order
        return picking

    def _send(self, picking, *responses):
        with mock_neoship(make_response(json_data=LOGIN_OK), *responses) as calls:
            picking.send_to_shipper()
        return calls

    def _sent_package(self, calls):
        create_call = next(call for call in calls if '/bulk-create-and-print/' in call['url'])
        return create_call['json']['packages'][0]

    def test_send_creates_shipment_with_label(self):
        picking = self._picking()
        calls = self._send(picking, NOT_FOUND, created(), label())

        self.assertTrue(calls[2]['url'].endswith('/package/bulk-create-and-print/2'))
        package = self._sent_package(calls)
        self.assertTrue(package['reference_number'].endswith(picking.name.replace('/', '-')))
        self.assertEqual(package['receiver_name'], 'Jan Testovaci')
        self.assertEqual(package['receiver_street'], 'Hlavna 1')
        self.assertEqual(package['receiver_state_code'], 'SK')
        self.assertEqual(package['receiver_phone'], '+421900123456')
        self.assertEqual(package['sender_email'], 'warehouse@example.com')
        self.assertEqual(package['weight'], 0.8)
        self.assertEqual(package['count_of_packages'], 1)
        self.assertNotIn('cod_price', package)

        self.assertEqual(picking.neoship_package_id, 501)
        self.assertEqual(picking.carrier_tracking_ref, 'TRK1')
        self.assertEqual(picking.neoship_reference, package['reference_number'])
        attachment = self.env['ir.attachment'].search(
            [('res_model', '=', 'stock.picking'), ('res_id', '=', picking.id)]
        )
        self.assertEqual(attachment.name, 'LabelShipping-neoship-TRK1.pdf')
        self.assertEqual(attachment.raw, PDF)

    def test_reference_is_transfer_name_with_single_company(self):
        picking = self._picking()
        self.env.registry.clear_cache()
        with patch.object(type(self.env['res.company']), 'search_count', return_value=1):
            package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
        self.assertEqual(package['reference_number'], picking.name.replace('/', '-'))

    def test_reference_has_company_prefix_with_several_companies(self):
        self.env['res.company'].create({'name': 'Second Company'})
        picking = self._picking()
        package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
        expected = f'C{picking.company_id.id}-{picking.name.replace("/", "-")}'
        self.assertEqual(package['reference_number'], expected)
        self.assertEqual(picking.neoship_reference, expected)

    def test_company_count_is_cached_until_a_company_is_created(self):
        self.env.registry.clear_cache()
        with patch.object(type(self.env['res.company']), 'search_count', return_value=1) as search_count:
            self._send(self._picking(), NOT_FOUND, created(), label())
            self._send(self._picking(), NOT_FOUND, created(502, 'TRK2'), label())
        self.assertEqual(search_count.call_count, 1)

        self.env['res.company'].create({'name': 'Second Company'})
        self.assertTrue(self.env['stock.picking']._neoship_multi_company())

    def test_existing_shipment_is_found_by_reference(self):
        picking = self._picking()
        calls = self._send(picking, found(), label())
        self.assertFalse([call for call in calls if '/bulk-create-and-print/' in call['url']])
        self.assertEqual(picking.neoship_package_id, 777)
        self.assertEqual(picking.carrier_tracking_ref, 'TRK-OLD')

    def test_existing_shipment_with_same_cash_on_delivery_is_linked(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        picking = self._picking()
        existing = found(cod_price=f'{self.order.amount_total:.4f}', cod_currency_code=self.order.currency_id.name)
        calls = self._send(picking, existing, label())
        self.assertFalse([call for call in calls if '/package/cancel/' in call['url']])
        self.assertEqual(picking.neoship_package_id, 777)
        self.assertEqual(picking.neoship_cod_amount, self.order.amount_total)

    def test_existing_shipment_with_different_data_is_replaced(self):
        picking = self._picking()
        picking.write({'neoship_cod_manual': True, 'neoship_cod_manual_amount': 12.5})
        existing = found(receiver_street='Stara 9', cod_price='30.0000', cod_currency_code='EUR')
        calls = self._send(picking, existing, make_response(json_data={}), created(), label())

        self.assertEqual(calls[2]['url'], TEST_URL + '/package/cancel/777')
        self.assertEqual(self._sent_package(calls)['cod_price'], 12.5)
        self.assertEqual(picking.neoship_package_id, 501)
        self.assertEqual(picking.carrier_tracking_ref, 'TRK1')
        self.assertEqual(picking.neoship_cod_amount, 12.5)
        message = picking.message_ids.filtered(lambda m: 'replaced by shipment TRK1' in (m.body or ''))
        self.assertIn('receiver_street: Stara 9', message.body)
        self.assertIn('cod_price: 30.0 → 12.5', message.body)

    def test_existing_shipment_with_different_data_already_handed_over(self):
        picking = self._picking()
        with (
            mock_neoship(make_response(json_data=LOGIN_OK), found(receiver_zip='99999'), NOT_FOUND) as calls,
            self.assertRaisesRegex(UserError, 'TRK-OLD .*can no longer be cancelled'),
        ):
            picking.send_to_shipper()
        self.assertFalse([call for call in calls if '/bulk-create-and-print/' in call['url']])
        self.assertFalse(picking.neoship_package_id)

    def test_unprinted_shipment_from_failed_attempt_is_replaced(self):
        picking = self._picking()
        leftover = make_response(json_data=[{'id': 33999, 'tracking_number': None}])
        calls = self._send(picking, leftover, make_response(json_data={}), created(), label())
        self.assertEqual((calls[2]['method'], calls[2]['url'].rsplit('/api', 1)[1]), ('DELETE', '/package/33999'))
        self.assertTrue(calls[3]['url'].endswith('/bulk-create-and-print/2'))
        self.assertEqual(picking.neoship_package_id, 501)

    def test_created_shipment_without_tracking_number_is_an_error(self):
        picking = self._picking()
        with self.assertRaisesRegex(UserError, 'returned no tracking number'):
            self._send(picking, NOT_FOUND, created(tracking_number=None))
        self.assertFalse(picking.neoship_package_id)

    def test_several_shipments_with_same_reference_need_review(self):
        picking = self._picking()
        existing = make_response(json_data=[{'id': 1, 'tracking_number': 'A'}, {'id': 2, 'tracking_number': 'B'}])
        with self.assertRaisesRegex(UserError, 'Several Neoship shipments'):
            self._send(picking, existing)
        self.assertFalse(picking.neoship_package_id)

    def test_transfer_locked_by_another_send_is_refused(self):
        picking = self._picking()
        with (
            patch.object(type(picking), 'lock_for_update', side_effect=LockError('locked')),
            mock_neoship() as calls,
            self.assertRaisesRegex(UserError, 'already being sent to Neoship'),
        ):
            picking.send_to_shipper()
        self.assertFalse(calls)

    def test_timeout_on_create_explains_safe_retry(self):
        picking = self._picking()
        with self.assertRaisesRegex(UserError, 'no duplicate is created'):
            self._send(picking, NOT_FOUND, requests.exceptions.ReadTimeout())
        self.assertFalse(picking.neoship_package_id)

    def test_label_failure_keeps_shipment_and_label_can_be_downloaded_again(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), make_response(500, {'message': 'Storage down'}))
        self.assertEqual(picking.neoship_package_id, 501)
        self.assertIn('Storage down', picking.neoship_error)

        with mock_neoship(make_response(json_data=LOGIN_OK), label()) as calls:
            picking.action_neoship_download_label()
        self.assertTrue(calls[-1]['url'].endswith('/package/501/label'))
        self.assertFalse(picking.neoship_error)
        self.assertTrue(
            self.env['ir.attachment'].search_count(
                [('res_model', '=', 'stock.picking'), ('res_id', '=', picking.id), ('name', 'like', 'LabelShipping')]
            )
        )

    def test_shipment_is_sent_to_production_environment(self):
        self.carrier.prod_environment = True
        self.carrier.write({'neoship_shipper_id': 2, 'neoship_shipper_code': 'SPS', 'neoship_shipper_name': 'SPS'})
        picking = self._picking()
        calls = self._send(picking, NOT_FOUND, created(), label())
        self.assertTrue(all(call['url'].startswith(PROD_URL) for call in calls))
        self.assertTrue(picking.neoship_prod_environment)

    def test_shipment_keeps_its_environment_after_carrier_switch(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        self.assertFalse(picking.neoship_prod_environment)
        self.carrier.prod_environment = True

        self.assertTrue(picking.carrier_tracking_url.startswith(TEST_TRACKING_URL))
        with mock_neoship(make_response(json_data=LOGIN_OK), label()) as calls:
            picking.action_neoship_download_label()
        self.assertEqual(calls[-1]['url'], TEST_URL + '/package/501/label')

        picking.state = 'done'
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data={})) as calls:
            picking.cancel_shipment()
        self.assertEqual(calls[-1]['url'], TEST_URL + '/package/cancel/501')

    def test_timeout_on_lookup_is_not_reported_as_possible_create(self):
        picking = self._picking()
        with self.assertRaisesRegex(UserError, 'did not respond in time') as error:
            self._send(picking, requests.exceptions.ReadTimeout())
        self.assertNotIn('may still be created', str(error.exception))

    def test_carrier_missing_from_price_list(self):
        picking = self._picking()
        with self.assertRaisesRegex(UserError, 'SPS is not in the price list'):
            self._send(picking, NOT_FOUND, NOT_FOUND)

    def test_reference_used_by_another_transfer_is_refused_before_calling_neoship(self):
        picking, other = self._picking(), self._picking()
        other.neoship_reference = picking._neoship_reference()
        with (
            mock_neoship() as calls,
            self.assertRaisesRegex(UserError, f'already used by transfer {other.name}'),
        ):
            picking.send_to_shipper()
        self.assertFalse(calls)

    def test_manual_cash_on_delivery_cannot_be_negative(self):
        picking = self._picking()
        with mute_logger('odoo.sql_db'), self.assertRaises(CheckViolation), self.cr.savepoint():
            picking.neoship_cod_manual_amount = -12.5
            picking.flush_recordset()

    def test_missing_recipient_contact_is_reported_before_calling_neoship(self):
        partner = self.env['res.partner'].create(
            {
                'name': 'No Contact',
                'street': 'Hlavna 2',
                'city': 'Kosice',
                'zip': '04001',
                'country_id': self.country_sk.id,
            }
        )
        picking = self._picking(order=self._create_order(partner))
        with (
            mock_neoship() as calls,
            self.assertRaisesRegex(UserError, r'Recipient No Contact is missing: email, phone'),
        ):
            picking.send_to_shipper()
        self.assertFalse(calls)

    def test_phone_whitespace_is_removed(self):
        self.customer.phone = '+421 905\u00a0123 456'
        package = self._sent_package(self._send(self._picking(), NOT_FOUND, created(), label()))
        self.assertEqual(package['receiver_phone'], '+421905123456')

    def test_contact_falls_back_to_order_customer(self):
        delivery_address = self.env['res.partner'].create(
            {
                'name': 'Delivery Address',
                'parent_id': self.customer.id,
                'type': 'delivery',
                'street': 'Dlha 3',
                'city': 'Presov',
                'zip': '08001',
                'country_id': self.country_sk.id,
                'email': False,
                'phone': False,
            }
        )
        picking = self._picking(partner=delivery_address)
        package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
        self.assertEqual(package['receiver_street'], 'Dlha 3')
        self.assertEqual(package['receiver_email'], 'jan@example.com')

    def test_neoship_validation_errors_are_shown(self):
        picking = self._picking()
        invalid = make_response(422, [{'reference_number': 'X', 'errors': {'receiver_zip': ['Neplatné PSČ.']}}])
        with self.assertRaisesRegex(UserError, 'receiver_zip: Neplatné PSČ.'):
            self._send(picking, NOT_FOUND, invalid)

    def test_low_credit_is_shown(self):
        picking = self._picking()
        with self.assertRaisesRegex(UserError, 'Your credit is low'):
            self._send(picking, NOT_FOUND, make_response(402, {'error': 'Your credit is low'}))

    def test_carrier_must_be_chosen(self):
        self.carrier.write({'neoship_shipper_id': False, 'neoship_shipper_code': False})
        with self.assertRaisesRegex(UserError, 'Choose the Neoship carrier'):
            self._picking().send_to_shipper()

    def test_cash_on_delivery_uses_order_total(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        picking = self._picking()
        package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
        self.assertEqual(package['cod_price'], self.order.amount_total)
        self.assertEqual(package['cod_currency_code'], self.order.currency_id.name)
        self.assertEqual(package['cod_reference'], self.order.name)
        self.assertEqual(picking.neoship_cod_amount, self.order.amount_total)

    def test_second_cash_on_delivery_shipment_needs_manual_amount(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        self._send(self._picking(), NOT_FOUND, created(), label())
        backorder = self._picking(quantity=1)
        with self.assertRaisesRegex(UserError, 'already has a cash on delivery shipment'):
            self._send(backorder)

        backorder.write({'neoship_cod_manual': True, 'neoship_cod_manual_amount': 12.5})
        package = self._sent_package(self._send(backorder, NOT_FOUND, created(502, 'TRK2'), label()))
        self.assertEqual(package['cod_price'], 12.5)

    def test_cash_on_delivery_locks_other_neoship_deliveries_of_order(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        picking, other = self._picking(), self._picking()
        cancelled = self._picking()
        cancelled.state = const.ODOO_PICKING_STATE_CANCEL
        self._picking().carrier_id = False
        locked = []
        with patch.object(
            type(picking), 'lock_for_update', autospec=True, side_effect=lambda records, **kw: locked.append(records)
        ):
            self._send(picking, NOT_FOUND, created(), label())
        self.assertEqual(locked, [picking, other])

    def test_cash_on_delivery_refused_while_other_delivery_of_order_is_locked(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        picking, other = self._picking(), self._picking()

        def lock(records, **kw):
            if records == other:
                raise LockError('locked')

        with (
            patch.object(type(picking), 'lock_for_update', autospec=True, side_effect=lock),
            mock_neoship() as calls,
            self.assertRaisesRegex(UserError, f'Another transfer of order {self.order.name} is being processed'),
        ):
            picking.send_to_shipper()
        self.assertFalse(calls)

    def test_manual_zero_cash_on_delivery_sends_none(self):
        self.carrier.neoship_cod_domain = f"[('partner_id', '=', {self.customer.id})]"
        picking = self._picking()
        picking.write({'neoship_cod_manual': True, 'neoship_cod_manual_amount': 0.0})
        package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
        self.assertNotIn('cod_price', package)

    def test_packeta_home_delivery(self):
        self.carrier.write(
            {
                'neoship_shipper_code': 'Packeta',
                'neoship_carrier_type': 131,
                'neoship_carrier_type_name': 'SK Packeta Home HD',
                'neoship_carrier_type_country_id': self.country_sk.id,
            }
        )
        package = self._sent_package(self._send(self._picking(), NOT_FOUND, created(), label()))
        self.assertEqual(package['carrier_type'], 131)
        self.assertNotIn('parcelshop', package)

    def test_packeta_home_delivery_to_another_country_is_refused_before_calling_neoship(self):
        self.carrier.write(
            {
                'neoship_shipper_code': 'Packeta',
                'neoship_carrier_type': 106,
                'neoship_carrier_type_name': 'CZ Zásilkovna domů HD',
                'neoship_carrier_type_country_id': self.env.ref('base.cz').id,
            }
        )
        with (
            mock_neoship() as calls,
            self.assertRaisesRegex(UserError, 'CZ Zásilkovna domů HD .* delivers only to Czech'),
        ):
            self._picking().send_to_shipper()
        self.assertFalse(calls)

    def test_packeta_pickup_point_skips_home_delivery_country(self):
        self.carrier.write(
            {
                'neoship_shipper_code': 'Packeta',
                'neoship_carrier_type': 106,
                'neoship_carrier_type_country_id': self.env.ref('base.cz').id,
            }
        )
        self.order.neoship_parcelshop_id = 'PS-1234'
        package = self._sent_package(self._send(self._picking(), NOT_FOUND, created(), label()))
        self.assertEqual(package['parcelshop'], 'PS-1234')

    def test_packeta_pickup_point_does_not_send_carrier_type(self):
        self.carrier.write({'neoship_shipper_code': 'Packeta', 'neoship_carrier_type': 131})
        self.order.neoship_parcelshop_id = 'PS-1234'
        package = self._sent_package(self._send(self._picking(), NOT_FOUND, created(), label()))
        self.assertEqual(package['parcelshop'], 'PS-1234')
        self.assertNotIn('carrier_type', package)

    def test_packeta_weight_limit(self):
        self.carrier.write({'neoship_shipper_code': 'Packeta', 'neoship_carrier_type': 131})
        self.product.weight = 10
        with self.assertRaisesRegex(UserError, 'Packeta needs a weight'):
            self._picking().send_to_shipper()

    def test_default_weight_is_used_without_product_weight(self):
        self.product.weight = 0
        self.carrier.neoship_default_weight = 1.5
        package = self._sent_package(self._send(self._picking(), NOT_FOUND, created(), label()))
        self.assertEqual(package['weight'], 1.5)

    def test_cancel_shipment(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        picking.state = 'done'
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data={})) as calls:
            picking.cancel_shipment()
        self.assertTrue(calls[-1]['url'].endswith('/package/cancel/501'))
        self.assertFalse(picking.neoship_package_id)
        self.assertFalse(picking.carrier_tracking_ref)

    def test_cancel_after_handover_is_refused(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        with mock_neoship(make_response(json_data=LOGIN_OK), NOT_FOUND):
            action = picking.cancel_shipment()
        self.assertIn('can no longer cancel shipment TRK1', action['params']['message'])
        self.assertTrue(picking.neoship_cancel_refused)
        self.assertIn('can no longer cancel', picking.neoship_error)
        self.assertEqual(picking.neoship_package_id, 501)
        self.assertEqual(picking.carrier_tracking_ref, 'TRK1')

    def test_order_can_be_cancelled_after_shipment_cancel_is_refused(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        picking.state = 'done'
        with mock_neoship(make_response(json_data=LOGIN_OK), NOT_FOUND):
            picking.cancel_shipment()
        self.order.action_cancel()
        self.assertEqual(self.order.state, 'cancel')
        self.assertEqual(picking.neoship_package_id, 501)

    def test_order_with_active_shipment_cannot_be_cancelled(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        with self.assertRaisesRegex(UserError, f'Cancel the Neoship shipments first.*{picking.name} \\(TRK1\\)'):
            self.order.action_cancel()
        self.assertNotEqual(self.order.state, 'cancel')

        picking.state = 'done'
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data={})):
            picking.cancel_shipment()
        self.order.action_cancel()
        self.assertEqual(self.order.state, 'cancel')

    def test_order_shows_its_neoship_shipments(self):
        picking = self._picking()
        self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        self.assertEqual(self.order.neoship_shipment_count, 1)
        action = self.order.action_view_neoship_shipments()
        self.assertEqual(self.env['stock.picking'].search(action['domain']), picking)

        picking.state = 'done'
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data={})):
            picking.cancel_shipment()
        self.assertEqual(self.order.neoship_shipment_count, 0)

    def test_label_opens_without_calling_neoship(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        attachment = picking._neoship_label()
        with mock_neoship() as calls:
            action = picking.action_neoship_open_label()
        self.assertFalse(calls)
        self.assertEqual(action['url'], f'/web/content/{attachment.id}')

    def test_missing_label_is_downloaded_before_opening(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), make_response(500, {'message': 'Storage down'}))
        with mock_neoship(make_response(json_data=LOGIN_OK), label()):
            action = picking.action_neoship_open_label()
        attachment = picking._neoship_label()
        self.assertEqual(attachment.raw, PDF)
        self.assertEqual(action['url'], f'/web/content/{attachment.id}')

    def test_salesman_opens_shipment_label_from_order(self):
        picking = self._picking()
        self._send(picking, NOT_FOUND, created(), label())
        user = new_test_user(self.env, login='neoship_salesman', groups='sales_team.group_sale_salesman')
        self.order.user_id = user
        order = self.order.with_user(user)
        self.assertEqual(order.neoship_shipment_count, 1)
        shipment = self.env['stock.picking'].with_user(user).search(order.action_view_neoship_shipments()['domain'])
        action = shipment.action_neoship_open_label()
        self.assertEqual(action['url'], f'/web/content/{picking._neoship_label().id}')

    def test_validation_by_warehouse_user_sends_shipment(self):
        self.warehouse.out_type_id.print_label = True
        user = new_test_user(self.env, login='neoship_stock_user', groups='stock.group_stock_user')
        picking = self._picking().with_user(user)
        picking.action_confirm()
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        with mock_neoship(make_response(json_data=LOGIN_OK), NOT_FOUND, created(), label()):
            picking.button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.carrier_tracking_ref, 'TRK1')

    def test_unique_reference(self):
        first, second = self._picking(), self._picking()
        first.neoship_reference = 'SAME'
        with mute_logger('odoo.sql_db'), self.assertRaises(UniqueViolation), self.cr.savepoint():
            second.neoship_reference = 'SAME'
            second.flush_recordset()
