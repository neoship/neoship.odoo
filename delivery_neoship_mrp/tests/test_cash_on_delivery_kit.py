from odoo.tests import tagged

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.tests.common import NeoshipShippingCommon, created


@tagged('post_install', '-at_install')
class TestCashOnDeliveryKit(NeoshipShippingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier.neoship_cod_domain = f"[('partner_id', '=', {cls.customer.id})]"
        cls.coffee = cls.env['product.product'].create({'name': 'Coffee', 'type': 'consu'})
        cls.mug = cls.env['product.product'].create({'name': 'Mug', 'type': 'consu'})
        cls.gift_set = cls.env['product.product'].create({'name': 'Gift Set', 'type': 'consu'})
        cls.env['mrp.bom'].create(
            {
                'product_tmpl_id': cls.gift_set.product_tmpl_id.id,
                'type': const.ODOO_BOM_TYPE_KIT,
                'bom_line_ids': [
                    (0, 0, {'product_id': cls.coffee.id, 'product_qty': 1}),
                    (0, 0, {'product_id': cls.mug.id, 'product_qty': 2}),
                ],
            }
        )
        cls.order = cls.env['sale.order'].create(
            {
                'partner_id': cls.customer.id,
                'order_line': [
                    (
                        0,
                        0,
                        {
                            'product_id': cls.gift_set.id,
                            'product_uom_qty': 2,
                            'price_unit': 30.0,
                            'tax_ids': [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        cls.order.action_confirm()

    def _cod(self, picking, package_id=501):
        calls = self._send_new(picking, created(package_id, f'TRK{package_id}'))
        return self._sent_package(calls).get('cod_price')

    def test_kit_is_collected_per_complete_set(self):
        first = self.order.picking_ids
        backorder = self._validate(first, {self.coffee: 1, self.mug: 2})
        self.assertEqual(self._cod(first), 30.0)

        self._validate(backorder)
        self.assertEqual(self._cod(backorder, 502), 30.0)

    def test_kit_completed_over_several_deliveries(self):
        first = self.order.picking_ids
        second = self._validate(first, {self.coffee: 1, self.mug: 1})
        third = self._validate(second, {self.coffee: 1, self.mug: 2})
        self._validate(third)
        amounts = [self._cod(picking, 501 + index) for index, picking in enumerate(first | second | third)]
        self.assertEqual(amounts, [None, 30.0, 30.0])
