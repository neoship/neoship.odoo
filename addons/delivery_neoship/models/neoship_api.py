import requests

PROD_URL = 'https://apiserver.neoship.sk/api'
TEST_URL = 'https://t-we-nshp-api-01-app.azurewebsites.net/api'


class NeoshipError(Exception):
    pass


class NeoshipAuthError(NeoshipError):
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

        if response.status_code == 401:
            raise NeoshipAuthError(self._error_message(response))
        if not response.ok:
            raise NeoshipError(self._error_message(response))
        if 'application/json' in response.headers.get('Content-Type', ''):
            return response.json()
        return response.content

    @staticmethod
    def _error_message(response):
        try:
            message = response.json().get('message')
        except ValueError:
            message = None
        return f'HTTP {response.status_code}: {message}' if message else f'HTTP {response.status_code}'
