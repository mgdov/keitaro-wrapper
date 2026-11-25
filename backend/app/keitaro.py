import httpx
from fastapi import HTTPException

from app.config import Settings


class KeitaroClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport

    def request(self, method: str, path: str, data=None):
        key = self.settings.keitaro_api_key.get_secret_value()
        if not key:
            raise HTTPException(503, 'Укажите KEITARO_API_KEY в окружении backend.')
        try:
            with httpx.Client(timeout=self.settings.request_timeout, transport=self.transport,
                              headers={'Api-Key': key, 'Accept': 'application/json',
                                       'User-Agent': 'Tadzhibov-Keitaro-Wrapper/1.0'}) as client:
                response = client.request(method, self.settings.keitaro_base_url.rstrip('/') + path, json=data)
        except httpx.RequestError:
            raise HTTPException(502, 'Keitaro недоступен. Результат записи может быть неопределённым; проверьте журнал и повторно загрузите кампанию.') from None
        if response.is_error:
            raise HTTPException(502, f'Keitaro вернул HTTP {response.status_code} для {method} {path}. Проверьте журнал стенда.')
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, 'Keitaro вернул некорректный JSON.') from None

    def get(self, path):
        return self.request('GET', path)

