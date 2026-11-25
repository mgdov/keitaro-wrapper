from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./keitaro.db'
    keitaro_base_url: str = 'https://keitaro-for-tests.etolegko.com/admin_api/v1'
    keitaro_api_key: SecretStr = SecretStr('')
    campaign_prefix: str = 'test_tadzhibov_'
    request_timeout: float = Field(default=20, gt=0, le=120)

    @field_validator('campaign_prefix')
    @classmethod
    def prefix(cls, value: str) -> str:
        import re
        if not re.fullmatch(r'test_[a-z]+_', value):
            raise ValueError('Префикс должен иметь вид test_surname_')
        return value

