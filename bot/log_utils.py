"""
Утилиты для работы с логами.

Предоставляет функции для поиска последнего файла логов и отправки уведомлений администратору.
"""

import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


def get_latest_log_file(logs_dir: Path) -> Optional[Path]:
    """
    Находит последний файл лога по времени модификации.

    Ищет файлы bot.log, bot.log.1, bot.log.2 и т.д. и возвращает самый новый.

    Args:
        logs_dir: Директория с логами

    Returns:
        Путь к последнему файлу лога или None, если файлы не найдены
    """
    if not logs_dir.exists():
        logger.warning(f"Директория логов не существует: {logs_dir}")
        return None

    # Ищем все файлы, начинающиеся с bot.log
    log_files = []
    for file_path in logs_dir.iterdir():
        if file_path.is_file() and file_path.name.startswith("bot.log"):
            log_files.append(file_path)

    if not log_files:
        logger.warning(f"Файлы логов не найдены в {logs_dir}")
        return None

    # Сортируем по времени модификации (самый новый первым)
    log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return log_files[0]


async def send_admin_with_latest_log(
    bot: Bot, admin_id: int, message: str, logs_dir: Path
) -> None:
    """
    Отправляет сообщение администратору с прикрепленным последним файлом лога.

    Args:
        bot: Экземпляр aiogram Bot
        admin_id: ID администратора в Telegram
        message: Текстовое сообщение для отправки
        logs_dir: Директория с логами
    """
    if admin_id == 0:
        logger.warning("Admin ID не настроен, уведомление не отправлено")
        return

    try:
        # Отправляем текстовое сообщение
        await bot.send_message(chat_id=admin_id, text=message, parse_mode="HTML")
        logger.info(f"Отправлено уведомление администратору {admin_id}")

        # Находим последний файл лога
        latest_log = get_latest_log_file(logs_dir)
        if latest_log and latest_log.exists():
            try:
                log_content = latest_log.read_bytes()
                log_file = BufferedInputFile(log_content, filename=latest_log.name)
                await bot.send_document(
                    chat_id=admin_id,
                    document=log_file,
                    caption=f"📄 Latest log file: {latest_log.name}",
                )
                logger.info(
                    f"Отправлен файл лога {latest_log.name} администратору {admin_id}"
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке файла лога администратору: {e}")
        else:
            logger.warning(
                "Последний файл лога не найден, отправляется только сообщение"
            )

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления администратору: {e}")
