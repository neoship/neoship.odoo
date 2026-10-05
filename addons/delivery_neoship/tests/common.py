import json
from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase

REQUEST_PATH = 'odoo.addons.delivery_neoship.models.neoship_api.requests.request'


def make_response(status=200, json_data=None, content=b'', content_type='application/json'):
    response = requests.Response()
    response.status_code = status
    response.headers['Content-Type'] = content_type
    response._content = json.dumps(json_data).encode() if json_data is not None else content
    return response


@contextmanager
def mock_neoship(*responses):
    with patch(REQUEST_PATH, side_effect=list(responses)) as mock_request:
        yield mock_request


class NeoshipCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.delivery_product = cls.env['product.product'].create({
            'name': 'Neoship Delivery',
            'type': 'service',
            'list_price': 4.5,
        })
        cls.carrier = cls.env['delivery.carrier'].create({
            'name': 'Neoship Test',
            'delivery_type': 'neoship',
            'product_id': cls.delivery_product.id,
            'neoship_username': 'user@example.com',
            'neoship_password': 'secret-password',
            'neoship_shipper_id': '42',
        })
