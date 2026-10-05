import requests

PROD_URL = 'https://apiserver.neoship.sk/api'
TEST_URL = 'https://t-we-nshp-api-01-app.azurewebsites.net/api'


class NeoshipError(Exception):
    pass


class NeoshipAuthError(NeoshipError):
    pass


class NeoshipTimeout(NeoshipError):
    pass


class NeoshipClient:

    def __init__(self, base_url, username, password, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token = None

    def login(self):
        data = self._send('POST', '/login_check', json={
            'username': self.username,
            'password': self.password,
        })
        self._token = data['token']
        return self._token

    def request(self, method, path, **kwargs):
        if not self._token:
            self.login()
        try:
            return self._send(method, path, authenticated=True, **kwargs)
        except NeoshipAuthError:
            self.login()
            return self._send(method, path, authenticated=True, **kwargs)

    def _send(self, method, path, authenticated=False, **kwargs):
        headers = kwargs.pop('headers', {})
        if authenticated:
            headers['Authorization'] = f'Bearer {self._token}'
        try:
            response = requests.request(
                method, self.base_url + path, headers=headers, timeout=self.timeout, **kwargs,
            )
        except requests.exceptions.Timeout as e:
            raise NeoshipTimeout(f'Neoship did not respond in time ({method} {path})') from e
        except requests.exceptions.RequestException as e:
            raise NeoshipError(f'Cannot connect to Neoship ({method} {path})') from e

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
