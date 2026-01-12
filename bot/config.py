"""
Настройки для телеграм бота.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота из переменных окружения."""

    bot_token: str
    master_key: str  # 32 bytes hex для шифрования
    rpc_url: str  # URL RPC ноды BNB Chain
    admin_telegram_id: int = 0  # ID администратора для команды /get_db

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Игнорировать лишние переменные из .env
    )


settings = Settings()

# Константы для работы с рынками
TICK_SIZE = 0.001  # Размер тика для цен на predict.fun
