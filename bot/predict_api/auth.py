"""
Аутентификация в Predict.fun API.

Реализует получение и обновление JWT токена для работы с API.
Поддерживает только Predict accounts (смарт-кошельки).
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

import requests
from predict_sdk import ChainId, OrderBuilder, OrderBuilderOptions
from requests.exceptions import ProxyError, RequestException, Timeout

logger = logging.getLogger(__name__)

JWT_REQUEST_TIMEOUT_SECONDS = 30
JWT_REQUEST_MAX_ATTEMPTS = 3
JWT_RETRYABLE_STATUS_CODES = {502, 503, 504}
JWT_RETRY_BASE_DELAY_SECONDS = 1.0
JWT_REFRESH_COOLDOWN_SECONDS = 60


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


def _is_retryable_status(status_code: int) -> bool:
    """Проверяет, можно ли повторить запрос по статус-коду."""
    return status_code in JWT_RETRYABLE_STATUS_CODES


def _format_request_error(context: str, error: Exception) -> str:
    """Формирует краткое описание ошибки запроса."""
    return f"{context}: {error.__class__.__name__}: {error}"


async def _sleep_with_backoff(attempt: int) -> None:
    """Ожидает перед повторной попыткой с экспоненциальной задержкой."""
    delay = JWT_RETRY_BASE_DELAY_SECONDS * (2**attempt)
    await asyncio.sleep(delay)


async def get_jwt_token_predict_account(
    api_key: str,
    wallet_address: str,
    private_key: str,
    proxies: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Получить JWT токен для Predict account (смарт-кошелька).

    Args:
        api_key: API ключ Predict.fun
        wallet_address: Адрес Predict account (deposit address)
        private_key: Приватный ключ Privy Wallet (можно экспортировать из настроек аккаунта)
        proxies: Словарь с прокси для requests в формате {'http': '...', 'https': '...'} (опционально)

    Returns:
        Кортеж (JWT токен, описание ошибки).
    """
    last_error: Optional[str] = None
    for attempt in range(JWT_REQUEST_MAX_ATTEMPTS):
        try:
            # Создаем OrderBuilder для Predict account
            chain_id = get_chain_id()
            builder = OrderBuilder.make(
                chain_id,
                private_key,
                OrderBuilderOptions(predict_account=wallet_address),
            )

            # Шаг 1: Получаем сообщение для подписи
            api_base_url = get_api_base_url()
            try:
                message_response = requests.get(
                    f"{api_base_url}/auth/message",
                    headers={"x-api-key": api_key},
                    timeout=JWT_REQUEST_TIMEOUT_SECONDS,
                    proxies=proxies,
                )
            except Timeout as e:
                last_error = _format_request_error(
                    "Таймаут при получении auth message", e
                )
                logger.warning(last_error)
                if attempt < JWT_REQUEST_MAX_ATTEMPTS - 1:
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error
            except ProxyError as e:
                last_error = _format_request_error(
                    "Ошибка прокси при получении auth message", e
                )
                logger.error(last_error)
                return None, last_error
            except RequestException as e:
                last_error = _format_request_error(
                    "Ошибка сети при получении auth message", e
                )
                logger.warning(last_error)
                if attempt < JWT_REQUEST_MAX_ATTEMPTS - 1:
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error

            if message_response.status_code != 200:
                last_error = (
                    f"Ошибка получения сообщения: {message_response.status_code}"
                )
                logger.error(f"{last_error} - {message_response.text}")
                if (
                    _is_retryable_status(message_response.status_code)
                    and attempt < JWT_REQUEST_MAX_ATTEMPTS - 1
                ):
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error

            message_data = message_response.json()
            message = message_data.get("data", {}).get("message")

            if not message:
                last_error = "Сообщение для подписи не найдено в ответе"
                logger.error(last_error)
                return None, last_error

            # Шаг 2: Подписываем сообщение через SDK (для Predict accounts)
            signature = builder.sign_predict_account_message(message)

            # Шаг 3: Получаем JWT токен
            body = {
                "signer": wallet_address,
                "message": message,
                "signature": signature,
            }

            try:
                jwt_response = requests.post(
                    f"{api_base_url}/auth",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                    },
                    json=body,
                    timeout=JWT_REQUEST_TIMEOUT_SECONDS,
                    proxies=proxies,
                )
            except Timeout as e:
                last_error = _format_request_error(
                    "Таймаут при получении JWT токена", e
                )
                logger.warning(last_error)
                if attempt < JWT_REQUEST_MAX_ATTEMPTS - 1:
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error
            except ProxyError as e:
                last_error = _format_request_error(
                    "Ошибка прокси при получении JWT токена", e
                )
                logger.error(last_error)
                return None, last_error
            except RequestException as e:
                last_error = _format_request_error(
                    "Ошибка сети при получении JWT токена", e
                )
                logger.warning(last_error)
                if attempt < JWT_REQUEST_MAX_ATTEMPTS - 1:
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error

            if jwt_response.status_code != 200:
                last_error = f"Ошибка получения JWT токена: {jwt_response.status_code}"
                logger.error(f"{last_error} - {jwt_response.text}")
                if (
                    _is_retryable_status(jwt_response.status_code)
                    and attempt < JWT_REQUEST_MAX_ATTEMPTS - 1
                ):
                    await _sleep_with_backoff(attempt)
                    continue
                return None, last_error

            jwt_data = jwt_response.json()
            jwt_token = jwt_data.get("data", {}).get("token")

            if not jwt_token:
                last_error = "JWT токен не найден в ответе"
                logger.error(last_error)
                return None, last_error

            logger.info(
                f"JWT токен успешно получен для Predict account {wallet_address}"
            )
            return jwt_token, None
        except Exception as e:
            last_error = _format_request_error(
                "Ошибка при получении JWT токена для Predict account", e
            )
            logger.error(last_error)
            return None, last_error

    return None, last_error


async def get_jwt_token(
    api_key: str,
    wallet_address: str,
    private_key: str,
    proxies: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    Получить JWT токен для работы с API.

    Поддерживает только Predict accounts (смарт-кошельки).

    Args:
        api_key: API ключ Predict.fun
        wallet_address: Deposit Address (адрес Predict Account)
        private_key: Приватный ключ Privy Wallet
        proxies: Словарь с прокси для requests в формате {'http': '...', 'https': '...'} (опционально)

    Returns:
        JWT токен или None в случае ошибки
    """
    token, _ = await get_jwt_token_predict_account(
        api_key, wallet_address, private_key, proxies
    )
    return token


async def get_jwt_token_with_error(
    api_key: str,
    wallet_address: str,
    private_key: str,
    proxies: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Получить JWT токен вместе с описанием ошибки.

    Returns:
        Кортеж (JWT токен, описание ошибки).
    """
    return await get_jwt_token_predict_account(
        api_key, wallet_address, private_key, proxies
    )


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
            - proxies: Словарь с прокси для requests (опционально)
        force_refresh: Принудительно обновить токен даже если он есть

    Returns:
        True если токен успешно обновлен, False в случае ошибки
    """
    # Защита от частых повторов после ошибки
    last_failure_ts = session.get("jwt_last_failure_ts")
    if last_failure_ts:
        elapsed = time.time() - last_failure_ts
        if elapsed < JWT_REFRESH_COOLDOWN_SECONDS:
            remaining = JWT_REFRESH_COOLDOWN_SECONDS - elapsed
            logger.warning(
                "Пропуск обновления JWT токена: последняя ошибка слишком свежая "
                f"(осталось {remaining:.1f} сек)"
            )
            return False

    # Если токен есть и не требуется принудительное обновление, пропускаем
    if not force_refresh and session.get("jwt_token"):
        return True

    # Получаем обязательные поля из сессии
    api_key = session.get("api_key")
    wallet_address = session.get("wallet_address")
    private_key = session.get("private_key")

    # Проверяем наличие обязательных полей
    if not api_key or not wallet_address or not private_key:
        logger.error("Отсутствуют обязательные поля в сессии для получения JWT токена")
        return False

    # Получаем новый токен
    jwt_token, error_detail = await get_jwt_token_with_error(
        api_key=api_key,
        wallet_address=wallet_address,
        private_key=private_key,
        proxies=session.get("proxies"),
    )

    if jwt_token:
        session["jwt_token"] = jwt_token
        session["jwt_last_error"] = None
        session["jwt_last_failure_ts"] = None
        return True
    else:
        session["jwt_last_error"] = error_detail or "Неизвестная ошибка JWT"
        session["jwt_last_failure_ts"] = time.time()
        logger.error("Не удалось обновить JWT токен")
        return False
