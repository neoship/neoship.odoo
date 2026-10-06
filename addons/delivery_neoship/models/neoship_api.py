from http import HTTPStatus

import requests

PROD_URL = 'https://apiserver.neoship.sk/api'
TEST_URL = 'https://t-we-nshp-api-01-app.azurewebsites.net/api'
PROD_TRACKING_URL = 'https://aplikacia.neoship.sk/tracking/'
TEST_TRACKING_URL = 'https://t-we-nshp-webapp-01-app.azurewebsites.net/tracking/'


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
        data = self._send(
            'POST',
            '/login_check',
            json={
                'username': self.username,
                'password': self.password,
            },
        )
        self.session.headers['Authorization'] = f'Bearer {data["token"]}'
        return data['token']

    def get_shippers(self):
        return self.request('GET', '/shipper/')

    def get_packeta_carriers(self):
        return self.request('GET', '/carrier/available')

    def create_packages(self, shipper_id, packages):
        return self.request('POST', f'/package/bulk-create-and-print/{shipper_id}', json={'packages': packages})

    def find_packages(self, reference_numbers):
        try:
            return self.request('POST', '/package/referencenumber/', json={'reference_numbers': reference_numbers})
        except NeoshipNotFoundError:
            return []

    def get_package(self, package_id):
        return self.request('GET', f'/package/{package_id}')

    def get_label(self, package_id):
        return self.request('GET', f'/package/{package_id}/label')

    def delete_package(self, package_id):
        return self.request('DELETE', f'/package/{package_id}')

    def cancel_package(self, package_id):
        return self.request('POST', f'/package/cancel/{package_id}')

    def request(self, method, path, **kwargs):
        if 'Authorization' not in self.session.headers:
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
        if 'application/json' in response.headers.get('Content-Type', ''):
            return response.json()
        return response.content

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
