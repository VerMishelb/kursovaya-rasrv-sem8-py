from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASS: str
    DB_NAME: str

    MQTT_BROKER: str
    MQTT_PORT: int
    MQTT_USERNAME: str
    MQTT_PASSWORD: str
    MQTT_QOS: int

    KAFKA_BOOTSTRAP_SERVERS: str
    KAFKA_MAX_BATCH_SIZE: int
    KAFKA_LINGER_MS: int

    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    @property
    def DATABASE_URL(self):
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")


config = Settings()