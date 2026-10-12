import json
from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import clear_token_cache

LOGIN_OK = {'token': 'token-1'}


def make_response(status=200, json_data=None, content=b'', content_type='application/json'):
    response = requests.Response()
    response.status_code = status
    response.headers['Content-Type'] = content_type
    response._content = json.dumps(json_data).encode() if json_data is not None else content
    return response


def login_ok():
    return make_response(json_data=LOGIN_OK)


PDF = b'%PDF-1.5 label'
STATUS_EXPORTED = {'id': 205, 'name': 'Exportovaná', 'group': 'exported'}
NOT_FOUND = make_response(404, {})


def created(package_id=501, tracking_number='TRK1', reference='REF', **values):
    return make_response(
        json_data=[{'id': package_id, 'reference_number': reference, 'tracking_number': tracking_number, **values}]
    )


def label():
    return make_response(content=PDF, content_type='application/pdf')


def tracked(picking, status=None):
    def response():
        status_data = STATUS_EXPORTED if status is None else status
        return make_response(
            json_data=[
                {
                    'id': parcel.neoship_id,
                    'reference_number': parcel.reference,
                    'tracking_number': parcel.tracking_ref,
                    'last_status': status_data,
                }
                for parcel in picking.neoship_parcel_ids
            ]
        )

    return response


@contextmanager
def mock_neoship(*responses):
    calls = []
    pending = list(responses)

    def request(session, method, url, **kwargs):
        calls.append({'method': method, 'url': url, 'headers': dict(session.headers), **kwargs})
        result = pending.pop(0)
        if callable(result):
            result = result()
        if isinstance(result, Exception):
            raise result
        return result

    with patch.object(requests.Session, 'request', autospec=True, side_effect=request):
        yield calls


class NeoshipCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.delivery_product = cls.env['product.product'].create(
            {
                'name': 'Neoship Delivery',
                'type': const.ODOO_PRODUCT_TYPE_SERVICE,
                'list_price': 4.5,
            }
        )
        cls.carrier = cls.env['delivery.carrier'].create(
            {
                'name': 'Neoship Test',
                'delivery_type': const.DELIVERY_TYPE,
                'product_id': cls.delivery_product.id,
                'neoship_username': 'user@example.com',
                'neoship_password': 'secret-password',
            }
        )

    def setUp(self):
        super().setUp()
        clear_token_cache()


class NeoshipShippingCommon(NeoshipCommon):
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

    def _send(self, picking, *responses):
        # Sending reads the status of the new parcels last; unused when sending fails earlier.
        with mock_neoship(login_ok(), *responses, tracked(picking)) as calls:
            picking.send_to_shipper()
        return calls

    def _sent_packages(self, calls):
        create_call = next(call for call in calls if '/bulk-create-and-print/' in call['url'])
        return create_call['json']['packages']

    def _sent_package(self, calls):
        return self._sent_packages(calls)[0]

    def _validate(self, picking, quantities=None):
        for move in picking.move_ids:
            quantity = move.product_qty if quantities is None else quantities.get(move.product_id, 0)
            move.move_line_ids.unlink()
            for part in filter(None, quantity if isinstance(quantity, tuple) else (quantity,)):
                self.env['stock.move.line'].create(
                    {
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_id.uom_id.id,
                        'quantity': part,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    }
                )
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        # The carrier is set only now, so validating does not send the shipment yet.
        picking.carrier_id = self.carrier
        return picking.backorder_ids
