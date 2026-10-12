from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import NOT_FOUND, NeoshipShippingCommon, created, label


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
        calls = self._send(picking, NOT_FOUND, created(package_id, f'TRK{package_id}'), label())
        return self._sent_package(calls).get('cod_price')

    def test_single_delivery_collects_order_total(self):
        order = self._order(self._line(self.mug, 3, 8.0), self._line(self.delivery_product, 1, 4.0))
        picking = order.picking_ids
        self._validate(picking)
        package = self._sent_package(self._send(picking, NOT_FOUND, created(), label()))
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
