"""
Аутентификация в Predict.fun API.

Реализует получение и обновление JWT токена для работы с API.
Поддерживает только Predict accounts (смарт-кошельки).
"""

import logging
from typing import Optional

import requests
from predict_sdk import ChainId, OrderBuilder, OrderBuilderOptions

logger = logging.getLogger(__name__)


# Базовый URL API (использует переменные окружения)
def get_api_base_url() -> str:
    """
    Получить базовый URL API с учетом TEST_MODE.

    Использует переменные окружения:
    - API_BASE_URL: Production API URL (по умолчанию: https://api.predict.fun/v1)
    - API_BASE_URL_TEST: Test API URL (по умолчанию: https://api-testnet.predict.fun/v1)
    - TEST_MODE: Если 'true', используется API_BASE_URL_TEST, иначе API_BASE_URL

    Если переменная окружения указана явно, она имеет приоритет над TEST_MODE.
    """
    import os

    # Проверяем TEST_MODE
    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"

    if test_mode:
        # Используем тестовый API URL
        api_url = os.getenv("API_BASE_URL_TEST", "https://api-testnet.predict.fun/v1")
    else:
        # Используем production API URL
        api_url = os.getenv("API_BASE_URL", "https://api.predict.fun/v1")

    # Убеждаемся, что URL заканчивается на /v1
    if not api_url.endswith("/v1"):
        api_url = api_url.rstrip("/") + "/v1"

    return api_url


def get_chain_id():
    """Получить ChainId с учетом TEST_MODE."""
    import os

    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
    if test_mode:
        return ChainId.BNB_TESTNET
    return ChainId.BNB_MAINNET


def get_rpc_url() -> str:
    """
    Получить RPC URL с учетом TEST_MODE.

    Использует переменные окружения:
    - RPC_URL: Production RPC URL (BNB Chain Mainnet)
    - RPC_URL_TEST: Test RPC URL (BNB Chain Testnet)
    - TEST_MODE: Если 'true', используется RPC_URL_TEST, иначе RPC_URL

    Returns:
        RPC URL для подключения к блокчейну
    """
    import os

    # Проверяем TEST_MODE
    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"

    if test_mode:
        # Используем тестовый RPC URL
        rpc_url = os.getenv("RPC_URL_TEST")
        if rpc_url:
            return rpc_url
        # Значение по умолчанию для testnet
        return "https://data-seed-prebsc-1-s1.binance.org:8545/"
    else:
        # Используем production RPC URL
        rpc_url = os.getenv("RPC_URL")
        if rpc_url:
            return rpc_url
        # Значение по умолчанию для mainnet
        return "https://bsc-dataseed.binance.org/"


async def get_jwt_token_predict_account(
    api_key: str, wallet_address: str, private_key: str
) -> Optional[str]:
    """
    Получить JWT токен для Predict account (смарт-кошелька).

    Args:
        api_key: API ключ Predict.fun
        wallet_address: Адрес Predict account (deposit address)
        private_key: Приватный ключ Privy Wallet (можно экспортировать из настроек аккаунта)

    Returns:
        JWT токен или None в случае ошибки
    """
    try:
        # Создаем OrderBuilder для Predict account
        chain_id = get_chain_id()
        builder = OrderBuilder.make(
            chain_id, private_key, OrderBuilderOptions(predict_account=wallet_address)
        )

        # Шаг 1: Получаем сообщение для подписи
        api_base_url = get_api_base_url()
        message_response = requests.get(
            f"{api_base_url}/auth/message", headers={"x-api-key": api_key}, timeout=30
        )

        if message_response.status_code != 200:
            logger.error(
                f"Ошибка получения сообщения: {message_response.status_code} - {message_response.text}"
            )
            return None

        message_data = message_response.json()
        message = message_data.get("data", {}).get("message")

        if not message:
            logger.error("Сообщение для подписи не найдено в ответе")
            return None

        # Шаг 2: Подписываем сообщение через SDK (для Predict accounts)
        signature = builder.sign_predict_account_message(message)

        # Шаг 3: Получаем JWT токен
        body = {
            "signer": wallet_address,
            "message": message,
            "signature": signature,
        }

        jwt_response = requests.post(
            f"{api_base_url}/auth",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
            },
            json=body,
            timeout=30,
        )

        if jwt_response.status_code != 200:
            logger.error(
                f"Ошибка получения JWT токена: {jwt_response.status_code} - {jwt_response.text}"
            )
            return None

        jwt_data = jwt_response.json()
        jwt_token = jwt_data.get("data", {}).get("token")

        if not jwt_token:
            logger.error("JWT токен не найден в ответе")
            return None

        logger.info(f"JWT токен успешно получен для Predict account {wallet_address}")
        return jwt_token

    except Exception as e:
        logger.error(f"Ошибка при получении JWT токена для Predict account: {e}")
        return None


async def get_jwt_token(
    api_key: str, wallet_address: str, private_key: str
) -> Optional[str]:
    """
    Получить JWT токен для работы с API.

    Поддерживает только Predict accounts (смарт-кошельки).

    Args:
        api_key: API ключ Predict.fun
        wallet_address: Deposit Address (адрес Predict Account)
        private_key: Приватный ключ Privy Wallet

    Returns:
        JWT токен или None в случае ошибки
    """
    return await get_jwt_token_predict_account(api_key, wallet_address, private_key)


async def refresh_jwt_token_if_needed(
    session: dict, force_refresh: bool = False
) -> bool:
    """
    Обновить JWT токен в сессии, если он истек или отсутствует.

    Args:
        session: Словарь сессии с ключами:
            - api_key: API ключ
            - wallet_address: Deposit Address (адрес Predict Account)
            - private_key: Приватный ключ Privy Wallet
            - jwt_token: Текущий JWT токен (может быть None)
        force_refresh: Принудительно обновить токен даже если он есть

    Returns:
        True если токен успешно обновлен, False в случае ошибки
    """
    # Если токен есть и не требуется принудительное обновление, пропускаем
    if not force_refresh and session.get("jwt_token"):
        return True

    # Получаем новый токен
    jwt_token = await get_jwt_token(
        api_key=session["api_key"],
        wallet_address=session["wallet_address"],
        private_key=session["private_key"],
    )

    if jwt_token:
        session["jwt_token"] = jwt_token
        return True
    else:
        logger.error("Не удалось обновить JWT токен")
        return False
