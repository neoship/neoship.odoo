import base64
import hashlib
import json
import time
from http import HTTPStatus

import requests

from .neoship_responses import ClosureResult, PacketaCarrier, Shipment, Shipper

PROD_URL = 'https://apiserver.neoship.sk/api'
TEST_URL = 'https://t-we-nshp-api-01-app.azurewebsites.net/api'
PROD_TRACKING_URL = 'https://aplikacia.neoship.sk/tracking/'
TEST_TRACKING_URL = 'https://t-we-nshp-webapp-01-app.azurewebsites.net/tracking/'
TOKEN_EXPIRY_MARGIN = 60

_tokens = {}


def clear_token_cache():
    _tokens.clear()


def token_expiry(token):
    try:
        payload = token.split('.')[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['exp'])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


class NeoshipError(Exception):
    pass


class NeoshipAuthError(NeoshipError):
    pass


class NeoshipNotFoundError(NeoshipError):
    pass


class NeoshipConnectionError(NeoshipError):
    pass


class NeoshipTimeout(NeoshipConnectionError):
    pass


class NeoshipResponseError(NeoshipError):
    pass


class NeoshipClient:
    def __init__(self, base_url, username, password, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        self.session.close()

    def login(self):
        self.session.headers.pop('Authorization', None)
        _tokens.pop(self._token_key(), None)
        method, path = 'POST', '/login_check'
        response = self._send(method, path, json={'username': self.username, 'password': self.password})
        data = self._json(method, path, response)
        if not isinstance(data, dict) or not data.get('token') or not isinstance(data['token'], str):
            raise NeoshipResponseError(f'unexpected response to {method} {path}')
        token = data['token']
        self.session.headers['Authorization'] = f'Bearer {token}'
        expiry = token_expiry(token)
        if expiry:
            _tokens[self._token_key()] = (token, expiry)
        return token

    def _token_key(self):
        return self.base_url, self.username, hashlib.sha256((self.password or '').encode()).hexdigest()

    def _cached_token(self):
        token, expiry = _tokens.get(self._token_key(), (None, 0))
        return token if expiry - TOKEN_EXPIRY_MARGIN > time.time() else None

    def get_active_shippers(self):
        return self._fetch('GET', '/shipper/active', Shipper, many=True)

    def get_packeta_carriers(self):
        return self._fetch('GET', '/carrier/available', PacketaCarrier, many=True)

    def create_packages(self, shipper_id, packages, print_type=None):
        payload = {'packages': packages}
        if print_type:
            payload['options'] = {'print_type': print_type}
        path = f'/package/bulk-create-and-print/{shipper_id}'
        shipments = self._fetch('POST', path, Shipment, many=True, json=payload)
        if len(shipments) != len(packages):
            raise NeoshipResponseError(
                f'unexpected response to POST {path}: {len(shipments)} shipments for {len(packages)} packages'
            )
        return shipments

    def find_packages(self, reference_numbers):
        try:
            return self._fetch(
                'POST', '/package/referencenumber/', Shipment, many=True, json={'reference_numbers': reference_numbers}
            )
        except NeoshipNotFoundError:
            return []

    def get_package(self, package_id):
        return self._fetch('GET', f'/package/{package_id}', Shipment)

    def get_label(self, package_id):
        path = f'/package/{package_id}/label'
        response = self._request('GET', path)
        if not response.content or 'application/json' in response.headers.get('Content-Type', ''):
            raise NeoshipResponseError(f'no file in response to GET {path}')
        return response.content

    def delete_package(self, package_id):
        self._request('DELETE', f'/package/{package_id}')

    def cancel_package(self, package_id):
        self._request('POST', f'/package/cancel/{package_id}')

    def close_day(self, action, date=None):
        payload = {'action': action}
        if date:
            payload['date'] = date.isoformat()
        return self._fetch('POST', '/package/bulk/', ClosureResult, json=payload)

    def _fetch(self, method, path, cls, many=False, **kwargs):
        data = self._json(method, path, self._request(method, path, **kwargs))
        try:
            return [cls.from_json(item) for item in data] if many else cls.from_json(data)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise NeoshipResponseError(f'unexpected response to {method} {path}') from e

    @staticmethod
    def _json(method, path, response):
        try:
            return response.json()
        except ValueError as e:
            raise NeoshipResponseError(f'invalid JSON in response to {method} {path}') from e

    def _request(self, method, path, **kwargs):
        if 'Authorization' not in self.session.headers:
            token = self._cached_token()
            if token:
                self.session.headers['Authorization'] = f'Bearer {token}'
            else:
                self.login()
        try:
            return self._send(method, path, **kwargs)
        except NeoshipAuthError:
            self.login()
            return self._send(method, path, **kwargs)

    def _send(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        except requests.exceptions.Timeout as e:
            raise NeoshipTimeout(f'Neoship did not respond in time ({method} {path})') from e
        except requests.exceptions.RequestException as e:
            raise NeoshipConnectionError(f'Cannot connect to Neoship ({method} {path})') from e

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise NeoshipAuthError(self._error_message(response))
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise NeoshipNotFoundError(self._error_message(response))
        if not response.ok:
            raise NeoshipError(self._error_message(response))
        return response

    @classmethod
    def _error_message(cls, response):
        try:
            detail = cls._error_detail(response.json())
        except ValueError:
            detail = None
        return f'HTTP {response.status_code}: {detail}' if detail else f'HTTP {response.status_code}'

    @staticmethod
    def _error_detail(data):
        if isinstance(data, dict):
            return data.get('message') or data.get('error')
        if isinstance(data, list):
            messages = [
                message
                for item in data
                if isinstance(item, dict)
                for message in NeoshipClient._error_messages(item.get('errors'))
            ]
            return '; '.join(messages)
        return None

    @staticmethod
    def _error_messages(errors):
        if isinstance(errors, dict):
            return [
                f'{field}: {message}'
                for field, messages in errors.items()
                for message in (messages if isinstance(messages, list) else [messages])
            ]
        if isinstance(errors, list):
            return [str(message) for message in errors]
        return [str(errors)] if errors else []
