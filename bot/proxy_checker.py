"""
Модуль для проверки работоспособности прокси.
Содержит функции для валидации формата, проверки работоспособности и фоновой задачи.
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple

import httpx
from database import (
    get_all_users,
    get_user,
    update_proxy_status,
)

logger = logging.getLogger(__name__)


def validate_proxy_format(proxy_str: str) -> Tuple[bool, str]:
    """
    Валидирует формат прокси строки.

    Args:
        proxy_str: Строка прокси в формате ip:port:login:password

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not proxy_str:
        return False, "Прокси не указан"

    if not isinstance(proxy_str, str):
        return False, "Прокси должен быть строкой"

    parts = proxy_str.split(":")
    if len(parts) != 4:
        return (
            False,
            f"Неверный формат прокси. Ожидается ip:port:login:password, получено {len(parts)} частей",
        )

    ip, port_str, login, password = parts

    # Проверяем IP
    if not ip or not ip.strip():
        return False, "IP адрес не может быть пустым"

    # Проверяем порт
    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            return False, f"Порт должен быть в диапазоне 1-65535, получено {port}"
    except ValueError:
        return False, f"Порт должен быть числом, получено: {port_str}"

    # Проверяем логин и пароль
    if not login or not login.strip():
        return False, "Логин не может быть пустым"

    if not password or not password.strip():
        return False, "Пароль не может быть пустым"

    return True, ""


def parse_proxy(proxy_str: str) -> Optional[dict]:
    """
    Парсит строку прокси формата ip:port:login:password.

    Args:
        proxy_str: Строка прокси в формате ip:port:login:password

    Returns:
        Словарь с ключами: {'host': str, 'port': int, 'username': str, 'password': str}
        Или None в случае ошибки
    """
    is_valid, error_message = validate_proxy_format(proxy_str)
    if not is_valid:
        logger.warning(f"Ошибка валидации прокси: {error_message}")
        return None

    try:
        parts = proxy_str.split(":")
        ip, port_str, username, password = parts

        return {
            "host": ip,
            "port": int(port_str),
            "username": username,
            "password": password,
        }
    except Exception as e:
        logger.error(f"Ошибка при парсинге прокси: {e}")
        return None


def parse_proxy_for_requests(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
    """
    Парсит прокси строку и преобразует в формат для requests.

    Args:
        proxy_str: Прокси в формате ip:port:login:password или None

    Returns:
        Словарь с ключами 'http' и 'https' для requests или None
    """
    if not proxy_str:
        return None

    parsed = parse_proxy(proxy_str)
    if not parsed:
        return None

    try:
        # Формат для requests: http://username:password@host:port
        proxy_url = f"http://{parsed['username']}:{parsed['password']}@{parsed['host']}:{parsed['port']}"

        return {"http": proxy_url, "https": proxy_url}
    except Exception as e:
        logger.warning(f"Ошибка преобразования прокси для requests: {e}")
        return None


async def check_proxy_health(proxy_str: str, timeout: float = 10.0) -> str:
    """
    Проверяет работоспособность прокси.

    Args:
        proxy_str: Прокси в формате ip:port:login:password
        timeout: Таймаут для проверки в секундах (по умолчанию 10)

    Returns:
        str: Статус прокси ('working' или 'failed')
    """
    parsed = parse_proxy(proxy_str)
    if not parsed:
        logger.error(f"Не удалось распарсить прокси для проверки: {proxy_str}")
        return "failed"

    host = parsed["host"]
    port = parsed["port"]
    username = parsed["username"]
    password = parsed["password"]

    delays = [0, 3, 5, 10]
    proxy_url_with_auth = f"http://{username}:{password}@{host}:{port}"

    for attempt, delay in enumerate(delays):
        if attempt > 0:
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(
                proxy=proxy_url_with_auth,
                timeout=timeout,
            ) as client:
                response = await client.get(
                    "http://httpbin.org/ip",
                    timeout=timeout,
                )

            if response.status_code == 200:
                logger.info(f"✅ Прокси {host}:{port} работает")
                return "working"

            logger.warning(
                f"❌ Прокси {host}:{port} вернул статус {response.status_code} (попытка {attempt + 1})"
            )
        except httpx.TimeoutException:
            logger.warning(
                f"⏱️ Таймаут при проверке прокси {host}:{port} (попытка {attempt + 1})"
            )
        except httpx.ProxyError as e:
            logger.warning(
                f"❌ Ошибка прокси {host}:{port}: {e} (попытка {attempt + 1})"
            )
        except Exception as e:
            logger.error(
                f"❌ Ошибка при проверке прокси {host}:{port}: {e} (попытка {attempt + 1})"
            )

    return "failed"


async def check_user_proxy(telegram_id: int, bot=None) -> Optional[str]:
    """
    Проверяет прокси для пользователя.

    Args:
        telegram_id: ID пользователя в Telegram
        bot: Экземпляр aiogram Bot для отправки уведомлений (опционально)

    Returns:
        str: Статус прокси ('working' или 'failed') или None в случае ошибки
    """
    user = await get_user(telegram_id)
    if not user:
        logger.warning(f"Пользователь {telegram_id} не найден")
        return None

    proxy_str = user.get("proxy_str")
    if not proxy_str:
        logger.info(f"У пользователя {telegram_id} не настроен прокси")
        return None

    old_status = user.get("proxy_status", "unknown")

    logger.info(f"Проверка прокси для пользователя {telegram_id}")

    # Проверяем прокси
    new_status = await check_proxy_health(proxy_str)

    # Обновляем статус в БД
    await update_proxy_status(telegram_id, new_status)

    # Отправляем уведомления при изменении статуса
    if bot and old_status != new_status:
        try:
            if old_status == "working" and new_status == "failed":
                # Прокси перестал работать
                message = f"""⚠️ <b>Proxy is not working</b>

Proxy for your account has stopped working.

Account: {user["wallet_address"][:10]}...

Proxy status: <b>failed</b>

Orders for this account will not be synchronized until the proxy is restored.

The proxy will be automatically checked every 10 minutes."""
                await bot.send_message(
                    chat_id=telegram_id, text=message, parse_mode="HTML"
                )
                logger.info(
                    f"Отправлено уведомление пользователю {telegram_id} о неработающем прокси"
                )
            elif old_status == "failed" and new_status == "working":
                # Прокси восстановился
                message = f"""✅ <b>Proxy restored</b>

Proxy for your account is working again.

Account: {user["wallet_address"][:10]}...

Proxy status: <b>working</b>

Order synchronization has been resumed."""
                await bot.send_message(
                    chat_id=telegram_id, text=message, parse_mode="HTML"
                )
                logger.info(
                    f"Отправлено уведомление пользователю {telegram_id} о восстановлении прокси"
                )
        except Exception as e:
            logger.error(
                f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}"
            )

    return new_status


async def async_check_all_proxies(bot=None):
    """
    Фоновая задача для проверки всех прокси.

    Проверяет всех пользователей с настроенным прокси и обновляет их статусы.
    Отправляет уведомления пользователям при изменении статуса с 'working' на 'failed'.

    Args:
        bot: Экземпляр aiogram Bot для отправки уведомлений (опционально)
    """
    logger.info("Начало проверки всех прокси")

    # Получаем всех пользователей
    users = await get_all_users()
    total_users = len(users)
    checked_users = 0
    failed_users = 0

    for telegram_id in users:
        user = await get_user(telegram_id)
        if user and user.get("proxy_str"):
            checked_users += 1
            status = await check_user_proxy(telegram_id, bot)
            if status == "failed":
                failed_users += 1
            # Небольшая задержка между проверками, чтобы не перегружать систему
            await asyncio.sleep(1)

    logger.info(
        f"Проверка прокси завершена: всего пользователей {total_users}, "
        f"с прокси {checked_users}, неработающих {failed_users}"
    )
