import base64
import json
import time

import requests

from odoo.tests import BaseCase, tagged

from odoo.addons.delivery_neoship.models.neoship_api import (
    NeoshipAuthError,
    NeoshipClient,
    NeoshipConnectionError,
    NeoshipError,
    NeoshipTimeout,
    clear_token_cache,
)

from .common import make_response, mock_neoship

LOGIN_OK = {'token': 'token-1', 'refresh_token': 'refresh-1'}


def jwt(expires_in):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + expires_in}).encode()).decode()
    return f'header.{payload.rstrip("=")}.signature'


@tagged('post_install', '-at_install')
class TestNeoshipClient(BaseCase):
    def setUp(self):
        super().setUp()
        clear_token_cache()
        self.addCleanup(clear_token_cache)
        self.client = self._client()

    def _client(self, password='secret-password'):
        client = NeoshipClient('https://neoship.test/api/', 'user@example.com', password)
        self.addCleanup(client.close)
        return client

    def test_valid_token_is_reused_by_the_next_client(self):
        token = jwt(3600)
        with mock_neoship(
            make_response(json_data={'token': token}),
            make_response(json_data={'id': 7}),
            make_response(json_data={'id': 8}),
        ) as calls:
            self.client.request('GET', '/package/7')
            self._client().request('GET', '/package/8')
        self.assertEqual([call['url'].rsplit('/', 1)[1] for call in calls], ['login_check', '7', '8'])
        self.assertEqual(calls[2]['headers']['Authorization'], f'Bearer {token}')

    def test_token_is_not_reused_without_expiry_close_to_expiry_or_with_other_password(self):
        for token, password in (('token-1', 'secret-password'), (jwt(30), 'secret-password'), (jwt(3600), 'other')):
            clear_token_cache()
            with (
                self.subTest(token=token, password=password),
                mock_neoship(
                    make_response(json_data={'token': token}),
                    make_response(json_data={'id': 7}),
                    make_response(json_data={'token': 'token-2'}),
                    make_response(json_data={'id': 8}),
                ) as calls,
            ):
                self._client().request('GET', '/package/7')
                self._client(password).request('GET', '/package/8')
            self.assertEqual(calls[2]['url'], 'https://neoship.test/api/login_check')

    def test_rejected_cached_token_logs_in_again(self):
        with mock_neoship(make_response(json_data={'token': jwt(3600)}), make_response(json_data={'id': 7})):
            self.client.request('GET', '/package/7')
        with mock_neoship(
            make_response(401, {'message': 'Invalid JWT Token'}),
            make_response(json_data={'token': 'token-2'}),
            make_response(json_data={'id': 8}),
        ) as calls:
            self.assertEqual(self._client().request('GET', '/package/8'), {'id': 8})
        self.assertEqual(calls[2]['headers']['Authorization'], 'Bearer token-2')

    def test_login_posts_credentials_and_stores_token(self):
        with mock_neoship(make_response(json_data=LOGIN_OK)) as calls:
            self.assertEqual(self.client.login(), 'token-1')
        self.assertEqual((calls[0]['method'], calls[0]['url']), ('POST', 'https://neoship.test/api/login_check'))
        self.assertEqual(calls[0]['json'], {'username': 'user@example.com', 'password': 'secret-password'})
        self.assertNotIn('Authorization', calls[0]['headers'])
        self.assertEqual(self.client.session.headers['Authorization'], 'Bearer token-1')

    def test_invalid_credentials(self):
        with (
            mock_neoship(make_response(401, {'code': 401, 'message': 'Invalid credentials'})),
            self.assertRaisesRegex(NeoshipAuthError, 'Invalid credentials'),
        ):
            self.client.login()

    def test_session_is_reused_with_bearer_token(self):
        with mock_neoship(
            make_response(json_data=LOGIN_OK),
            make_response(json_data={'id': 7}),
            make_response(json_data={'id': 8}),
        ) as calls:
            self.assertEqual(self.client.request('GET', '/package/7'), {'id': 7})
            self.assertEqual(self.client.request('GET', '/package/8'), {'id': 8})
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]['headers']['Authorization'], 'Bearer token-1')
        self.assertEqual(calls[2]['headers']['Authorization'], 'Bearer token-1')

    def test_request_logs_in_again_once_after_expired_token(self):
        self.client.session.headers['Authorization'] = 'Bearer expired'
        with mock_neoship(
            make_response(401, {'message': 'Expired JWT Token'}),
            make_response(json_data={'token': 'token-2'}),
            make_response(json_data={'id': 7}),
        ) as calls:
            self.assertEqual(self.client.request('GET', '/package/7'), {'id': 7})
        self.assertEqual(len(calls), 3)
        self.assertNotIn('Authorization', calls[1]['headers'])
        self.assertEqual(calls[2]['headers']['Authorization'], 'Bearer token-2')

    def test_binary_response_is_returned_as_bytes(self):
        self.client.session.headers['Authorization'] = 'Bearer token-1'
        with mock_neoship(make_response(content=b'%PDF-1.4', content_type='application/pdf')):
            self.assertEqual(self.client.request('GET', '/package/7/label'), b'%PDF-1.4')

    def test_api_error_contains_message(self):
        self.client.session.headers['Authorization'] = 'Bearer token-1'
        with (
            mock_neoship(make_response(400, {'message': 'Invalid zip code'})),
            self.assertRaisesRegex(NeoshipError, 'HTTP 400: Invalid zip code'),
        ):
            self.client.request('POST', '/package/42', json={})

    def test_field_errors_are_listed(self):
        detail = NeoshipClient._error_detail(
            [{'reference_number': 'X', 'errors': {'receiver_zip': ['Invalid ZIP.'], 'receiver_city': 'Required.'}}]
        )
        self.assertEqual(detail, 'receiver_zip: Invalid ZIP.; receiver_city: Required.')

    def test_package_level_errors_are_listed(self):
        detail = NeoshipClient._error_detail([{'reference_number': 'X', 'errors': ['Invalid package', 'No credit']}])
        self.assertEqual(detail, 'Invalid package; No credit')

    def test_single_error_message_is_kept_whole(self):
        self.assertEqual(NeoshipClient._error_detail([{'errors': 'Invalid package'}]), 'Invalid package')

    def test_timeout_is_distinguishable(self):
        self.client.session.headers['Authorization'] = 'Bearer token-1'
        with mock_neoship(requests.exceptions.ReadTimeout()), self.assertRaises(NeoshipTimeout):
            self.client.request('POST', '/package/42', json={})

    def test_connection_error(self):
        self.client.session.headers['Authorization'] = 'Bearer token-1'
        with mock_neoship(requests.exceptions.ConnectionError()), self.assertRaises(NeoshipConnectionError):
            self.client.request('GET', '/package/7')
