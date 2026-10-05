import requests

from odoo.tests import BaseCase, tagged

from odoo.addons.delivery_neoship.models.neoship_api import (
    NeoshipAuthError,
    NeoshipClient,
    NeoshipError,
    NeoshipTimeout,
)

from .common import make_response, mock_neoship

LOGIN_OK = {'token': 'token-1', 'refresh_token': 'refresh-1'}


@tagged('post_install', '-at_install')
class TestNeoshipClient(BaseCase):

    def setUp(self):
        super().setUp()
        self.client = NeoshipClient('https://neoship.test/api/', 'user@example.com', 'secret-password')

    def test_login_posts_credentials_and_stores_token(self):
        with mock_neoship(make_response(json_data=LOGIN_OK)) as mock_request:
            self.assertEqual(self.client.login(), 'token-1')
        method, url = mock_request.call_args.args
        self.assertEqual((method, url), ('POST', 'https://neoship.test/api/login_check'))
        self.assertEqual(mock_request.call_args.kwargs['json'], {
            'username': 'user@example.com',
            'password': 'secret-password',
        })

    def test_invalid_credentials(self):
        with mock_neoship(make_response(401, {'code': 401, 'message': 'Invalid credentials'})):
            with self.assertRaisesRegex(NeoshipAuthError, 'Invalid credentials'):
                self.client.login()

    def test_request_sends_bearer_token(self):
        with mock_neoship(
            make_response(json_data=LOGIN_OK),
            make_response(json_data={'id': 7}),
        ) as mock_request:
            self.assertEqual(self.client.request('GET', '/package/7'), {'id': 7})
        self.assertEqual(mock_request.call_args.kwargs['headers'], {'Authorization': 'Bearer token-1'})

    def test_request_logs_in_again_once_after_expired_token(self):
        self.client._token = 'expired'
        with mock_neoship(
            make_response(401, {'message': 'Expired JWT Token'}),
            make_response(json_data={'token': 'token-2'}),
            make_response(json_data={'id': 7}),
        ) as mock_request:
            self.assertEqual(self.client.request('GET', '/package/7'), {'id': 7})
        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_request.call_args.kwargs['headers'], {'Authorization': 'Bearer token-2'})

    def test_binary_response_is_returned_as_bytes(self):
        self.client._token = 'token-1'
        with mock_neoship(make_response(content=b'%PDF-1.4', content_type='application/pdf')):
            self.assertEqual(self.client.request('GET', '/package/7/label'), b'%PDF-1.4')

    def test_api_error_contains_message(self):
        self.client._token = 'token-1'
        with mock_neoship(make_response(400, {'message': 'Invalid zip code'})):
            with self.assertRaisesRegex(NeoshipError, 'HTTP 400: Invalid zip code'):
                self.client.request('POST', '/package/42', json={})

    def test_timeout_is_distinguishable(self):
        self.client._token = 'token-1'
        with mock_neoship(requests.exceptions.ReadTimeout()):
            with self.assertRaises(NeoshipTimeout):
                self.client.request('POST', '/package/42', json={})
