from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import TEST_URL

from .common import NOT_FOUND, NeoshipShippingCommon, cod_limits, created, login_ok, make_response, mock_neoship, stored


@tagged('post_install', '-at_install')
class TestCashOnDelivery(NeoshipShippingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier.neoship_cod_domain = f"[('partner_id', '=', {cls.customer.id})]"
        cls.vat = cls.env['account.tax'].create(
            {'name': 'VAT 23%', 'amount': 23.0, 'amount_type': 'percent', 'type_tax_use': 'sale'}
        )
        cls.beer = cls.env['product.product'].create({'name': 'Beer 0.5 l', 'type': 'consu'})
        cls.mug = cls.env['product.product'].create({'name': 'Mug', 'type': 'consu'})
        cls.pack_of_6 = cls.env.ref('uom.product_uom_pack_6')

    def _order(self, *lines):
        order = self.env['sale.order'].create(
            {'partner_id': self.customer.id, 'order_line': [(0, 0, line) for line in lines]}
        )
        order.action_confirm()
        return order

    def _line(self, product, quantity, price, **values):
        return {
            'product_id': product.id,
            'product_uom_qty': quantity,
            'price_unit': price,
            'tax_ids': [(6, 0, self.vat.ids)],
            **values,
        }

    def _cod(self, picking, package_id=501):
        calls = self._send_new(picking, created(package_id, f'TRK{package_id}'))
        return self._sent_package(calls).get('cod_price')

    def test_single_delivery_collects_order_total(self):
        order = self._order(self._line(self.mug, 3, 8.0), self._line(self.delivery_product, 1, 4.0))
        picking = order.picking_ids
        self._validate(picking)
        package = self._sent_package(self._send_new(picking, created()))
        self.assertEqual(package['cod_price'], 34.44)
        self.assertEqual(package['cod_price'], order.amount_total)
        self.assertEqual(package['cod_currency_code'], order.currency_id.name)
        self.assertEqual(package['cod_reference'], order.name)
        self.assertEqual(picking.neoship_parcel_ids.cod_amount, order.amount_total)

    def test_partial_deliveries_split_order_total(self):
        order = self._order(
            self._line(self.beer, 2, 12.0, product_uom_id=self.pack_of_6.id, discount=10.0),
            self._line(self.mug, 3, 8.0),
            {'display_type': 'line_section', 'name': 'Gifts'},
            self._line(self.delivery_product, 1, 4.0),
        )
        self.assertEqual(order.amount_total, 61.01)
        first = order.picking_ids
        # 5 bottles from two lots: 5/6 of a pack at 26.57 / 2 per pack, 2 mugs at 9.84 and the delivery 4.92.
        backorder = self._validate(first, {self.beer: (3, 2), self.mug: 2})
        self.assertEqual(self._cod(first), 35.67)

        self._validate(backorder, {self.beer: 7, self.mug: 1})
        self.assertEqual(self._cod(backorder, 502), 25.34)

    def test_last_delivery_collects_rounding_difference(self):
        order = self._order(self._line(self.mug, 3, 2.71))
        self.assertEqual(order.amount_total, 10.0)
        first = order.picking_ids
        second = self._validate(first, {self.mug: 1})
        third = self._validate(second, {self.mug: 1})
        self._validate(third)
        amounts = [self._cod(picking, 501 + index) for index, picking in enumerate(first | second | third)]
        self.assertEqual(amounts, [3.33, 3.33, 3.34])

    def test_services_stay_with_first_delivery_when_sent_again(self):
        order = self._order(self._line(self.mug, 2, 8.0), self._line(self.delivery_product, 1, 4.0))
        first = order.picking_ids
        backorder = self._validate(first, {self.mug: 1})
        self.assertEqual(first._neoship_cod_values()['cod_price'], 14.76)

        self._validate(backorder)
        self.assertEqual(backorder._neoship_cod_values()['cod_price'], 9.84)
        self.assertEqual(first._neoship_cod_values()['cod_price'], 14.76)

    def test_delivery_not_sent_through_neoship_is_deducted(self):
        order = self._order(self._line(self.mug, 2, 8.0), self._line(self.delivery_product, 1, 4.0))
        first = order.picking_ids
        backorder = self._validate(first, {self.mug: 1})
        first.carrier_id = False

        self._validate(backorder)
        self.assertEqual(self._cod(backorder), 9.84)

    def test_products_not_on_order_are_not_collected(self):
        order = self._order(self._line(self.mug, 2, 8.0))
        picking = order.picking_ids
        self.env['stock.move'].create(
            {
                'picking_id': picking.id,
                'product_id': self.beer.id,
                'product_uom_qty': 5,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            }
        )
        self._validate(picking, {self.mug: 1, self.beer: 5})
        self.assertEqual(self._cod(picking), 9.84)

    def test_line_with_zero_quantity_is_skipped(self):
        order = self._order(self._line(self.mug, 2, 8.0), self._line(self.beer, 0, 12.0))
        picking = order.picking_ids
        self._validate(picking, {self.mug: 1})
        self.assertEqual(self._cod(picking), 9.84)

    def test_negative_share_is_deducted_from_next_delivery(self):
        order = self._order(self._line(self.mug, 3, 8.0), self._line(self.delivery_product, 1, -20.0))
        self.assertEqual(order.amount_total, 4.92)
        first = order.picking_ids
        second = self._validate(first, {self.mug: 1})
        third = self._validate(second, {self.mug: 1})
        self._validate(third)
        # 9.84 - 24.60 = -14.76 for the first mug, the second mug brings it to -4.92.
        amounts = [self._cod(picking, 501 + index) for index, picking in enumerate(first | second | third)]
        self.assertEqual(amounts, [None, None, 4.92])

    def test_negative_order_total_needs_manual_amount(self):
        order = self._order(self._line(self.mug, 1, 8.0), self._line(self.delivery_product, 1, -20.0))
        picking = order.picking_ids
        self._validate(picking)
        with self.assertRaisesRegex(UserError, r'would be .*14\.76.*Set the cash on delivery amount manually'):
            picking._neoship_cod_values()

        picking.write({'neoship_cod_manual': True, 'neoship_cod_manual_amount': 5.0})
        self.assertEqual(self._cod(picking), 5.0)

    def test_dpd_reference_is_last_ten_digits_of_order_number(self):
        self.carrier.neoship_shipper_code = const.SHIPPER_CODE_DPD
        order = self._order(self._line(self.mug, 1, 8.0))
        order.name = 'S2026/10/000123456789'
        picking = order.picking_ids
        self._validate(picking)
        package = self._sent_package(self._send_new(picking, created()))
        self.assertEqual(package['cod_reference'], '0123456789')

    def test_dpd_reference_without_digits_uses_order_id(self):
        self.carrier.neoship_shipper_code = const.SHIPPER_CODE_DPD
        order = self._order(self._line(self.mug, 1, 8.0))
        order.name = 'WEB-ORDER'
        picking = order.picking_ids
        self._validate(picking)
        self.assertEqual(picking._neoship_cod_values()['cod_reference'], str(order.id))

    def test_dpd_reference_without_order_uses_transfer_number(self):
        self.carrier.neoship_shipper_code = const.SHIPPER_CODE_DPD
        picking = self.env['stock.picking'].create(
            {
                'picking_type_id': self.warehouse.out_type_id.id,
                'partner_id': self.customer.id,
                'carrier_id': self.carrier.id,
                'neoship_cod_manual': True,
                'neoship_cod_manual_amount': 5.0,
            }
        )
        picking.name = 'WH/OUT/00012'
        self.assertEqual(picking._neoship_cod_values()['cod_reference'], '00012')

    def _czk_picking(self, amount):
        order = self._order(self._line(self.mug, 1, 8.0))
        picking = order.picking_ids
        self._validate(picking)
        picking.write({'neoship_cod_manual': True, 'neoship_cod_manual_amount': amount})
        czk = self.env.ref('base.CZK')
        for currency, rate in ((czk, 25.0), (self.env.ref('base.EUR'), 1.0)):
            currency.active = True
            self.env['res.currency.rate'].create(
                {'currency_id': currency.id, 'rate': rate, 'name': fields.Date.context_today(picking)}
            )
        return picking, czk

    def test_cash_on_delivery_in_currency_neoship_collects_is_sent_unchanged(self):
        picking, czk = self._czk_picking(301.40)
        self.customer.country_id = self.env.ref('base.cz')
        with patch.object(type(picking), '_neoship_cod_currency', return_value=czk):
            calls = self._send_new(picking, created(), currencies=('CZK',))
        package = self._sent_package(calls)
        self.assertEqual((package['cod_price'], package['cod_currency_code']), (301.40, 'CZK'))
        self.assertEqual(calls[2]['url'], TEST_URL + '/codlimit/2/701')

    def test_cash_on_delivery_is_converted_to_currency_neoship_collects(self):
        picking, czk = self._czk_picking(301.40)
        with patch.object(type(picking), '_neoship_cod_currency', return_value=czk):
            calls = self._send_new(picking, created(), currencies=('EUR',))
        package = self._sent_package(calls)
        self.assertEqual((package['cod_price'], package['cod_currency_code']), (12.06, 'EUR'))
        self.assertEqual(calls[2]['url'], TEST_URL + '/codlimit/2/703')
        parcel = picking.neoship_parcel_ids
        self.assertEqual((parcel.cod_amount, parcel.cod_currency_id.name), (12.06, 'EUR'))
        message = picking.message_ids.filtered(lambda message: 'was converted' in (message.body or ''))
        self.assertIn('12.06', message.body)

    def test_cash_on_delivery_is_refused_where_carrier_does_not_collect_it(self):
        order = self._order(self._line(self.mug, 1, 8.0))
        picking = order.picking_ids
        self._validate(picking)
        with (
            mock_neoship(login_ok(), *cod_limits()) as calls,
            self.assertRaisesRegex(UserError, 'SPS does not collect cash on delivery in Slovakia'),
        ):
            picking.send_to_shipper()
        self.assertEqual(len(calls), 3)

    def test_cash_on_delivery_is_not_converted_without_exchange_rate(self):
        picking, czk = self._czk_picking(301.40)
        self.env.ref('base.HUF').rate_ids.unlink()
        with (
            patch.object(type(picking), '_neoship_cod_currency', return_value=czk),
            mock_neoship(login_ok(), *cod_limits('HUF')) as calls,
            self.assertRaisesRegex(UserError, 'Activate HUF and CZK with exchange rates'),
        ):
            picking.send_to_shipper()
        self.assertEqual(len(calls), 3)

    def test_shipment_is_cancelled_when_neoship_stores_other_currency(self):
        picking, czk = self._czk_picking(301.40)
        with (
            patch.object(type(picking), '_neoship_cod_currency', return_value=czk),
            mock_neoship(
                login_ok(),
                *cod_limits('CZK'),
                NOT_FOUND,
                created(),
                stored(cod_currency_code='EUR'),
                make_response(json_data={}),
            ) as calls,
            self.assertRaisesRegex(UserError, '301.4 EUR instead of 301.4 CZK .* TRK1 was cancelled'),
        ):
            picking.send_to_shipper()
        self.assertEqual(calls[-1]['url'], TEST_URL + '/package/cancel/501')

    def test_shipment_with_other_currency_that_cannot_be_cancelled_is_reported(self):
        picking, czk = self._czk_picking(301.40)
        with (
            patch.object(type(picking), '_neoship_cod_currency', return_value=czk),
            mock_neoship(
                login_ok(),
                *cod_limits('CZK'),
                NOT_FOUND,
                created(),
                stored(cod_currency_code='EUR'),
                make_response(500, {'message': 'Internal error'}),
            ) as calls,
            self.assertRaisesRegex(UserError, '301.4 EUR instead of 301.4 CZK .* TRK1 could not be cancelled'),
        ):
            picking.send_to_shipper()
        self.assertEqual(calls[-1]['url'], TEST_URL + '/package/cancel/501')
        self.assertFalse(picking.neoship_parcel_ids)
