import os
import unittest

from odoo.tests import BaseCase, TransactionCase, tagged

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import TEST_URL, NeoshipClient


def live_credentials():
    username = os.environ.get('NEOSHIP_USERNAME')
    password = os.environ.get('NEOSHIP_PASSWORD')
    if not username or not password:
        raise unittest.SkipTest('NEOSHIP_USERNAME and NEOSHIP_PASSWORD are not set')
    return username, password


@tagged('-standard', 'neoship_live')
class TestNeoshipLive(BaseCase):
    def setUp(self):
        super().setUp()
        username, password = live_credentials()
        self.client = NeoshipClient(os.environ.get('NEOSHIP_API') or TEST_URL, username, password)
        self.addCleanup(self.client.close)

    def test_login(self):
        self.assertTrue(self.client.login())

    def test_get_active_shippers(self):
        shippers = self.client.get_active_shippers()
        self.assertTrue(shippers)
        self.assertTrue(all(shipper.delivery_types for shipper in shippers))

    def test_get_packeta_carriers(self):
        carriers = self.client.get_packeta_carriers()
        self.assertTrue(carriers)
        self.assertTrue(all(len(carrier.state_code) == 2 for carrier in carriers))


@tagged('-standard', 'neoship_live_shipment')
class TestNeoshipLiveShipment(TransactionCase):
    """Creates and cancels a real SPS shipment on the Neoship test API."""

    def test_send_label_and_cancel(self):
        username, password = live_credentials()
        sk = self.env.ref('base.sk')
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        warehouse.partner_id.write(
            {
                'street': 'Mlynske nivy 5',
                'city': 'Bratislava',
                'zip': '82109',
                'country_id': sk.id,
                'email': 'test@neoship.sk',
                'phone': '+421900123456',
            }
        )
        customer = self.env['res.partner'].create(
            {
                'name': 'Jan Testovaci',
                'street': 'Hlavna 1',
                'city': 'Kosice',
                'zip': '04001',
                'country_id': sk.id,
                'email': 'test@neoship.sk',
                'phone': '+421900123456',
            }
        )
        carrier = self.env['delivery.carrier'].create(
            {
                'name': 'Neoship SPS live test',
                'delivery_type': const.DELIVERY_TYPE,
                'neoship_username': username,
                'neoship_password': password,
            }
        )
        with carrier._neoship_client() as client:
            sps = next(shipper for shipper in client.get_active_shippers() if shipper.shortcut == 'SPS')
        carrier._neoship_set_shipper(sps.id, sps.shortcut, sps.name)
        product = self.env['product.product'].create({'name': 'Live test item', 'type': 'consu', 'weight': 0.5})
        picking = self.env['stock.picking'].create(
            {
                'picking_type_id': warehouse.out_type_id.id,
                'partner_id': customer.id,
                'carrier_id': carrier.id,
                'move_ids': [
                    (
                        0,
                        0,
                        {
                            'product_id': product.id,
                            'product_uom_qty': 1,
                            'location_id': warehouse.lot_stock_id.id,
                            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
                        },
                    )
                ],
            }
        )

        picking.send_to_shipper()
        self.assertTrue(picking.neoship_package_id)
        self.assertTrue(picking.carrier_tracking_ref)
        attachment = self.env['ir.attachment'].search(
            [('res_model', '=', 'stock.picking'), ('res_id', '=', picking.id), ('name', 'like', 'LabelShipping')]
        )
        self.assertTrue(attachment.raw.startswith(b'%PDF'))

        picking.cancel_shipment()
        self.assertFalse(picking.neoship_package_id)
