import json
from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import clear_token_cache


def make_response(status=200, json_data=None, content=b'', content_type='application/json'):
    response = requests.Response()
    response.status_code = status
    response.headers['Content-Type'] = content_type
    response._content = json.dumps(json_data).encode() if json_data is not None else content
    return response


@contextmanager
def mock_neoship(*responses):
    calls = []
    pending = list(responses)

    def request(session, method, url, **kwargs):
        calls.append({'method': method, 'url': url, 'headers': dict(session.headers), **kwargs})
        result = pending.pop(0)
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
