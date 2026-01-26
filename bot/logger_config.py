"""
Модуль для настройки логирования в приложении.

Предоставляет функцию setup_root_logger для настройки корневого логгера
с ротацией логов и поддержкой уведомлений администратора.
"""

import asyncio
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Глобальная переменная для хранения функции отправки уведомлений админу
_admin_alert_callback = None
_last_alert_time = 0
_alert_cooldown = 300  # 5 минут между уведомлениями
_alert_ignore_patterns = ("Tunnel connection failed: 410 Gone",)


def _create_handlers(
    log_file: Path, file_level: int = logging.INFO, console_level: int = logging.WARNING
) -> tuple[RotatingFileHandler, logging.StreamHandler]:
    """
    Создает обработчики для файла и консоли с разными уровнями логирования.

    Args:
        log_file: Путь к файлу логов
        file_level: Уровень логирования для файла (по умолчанию INFO - все логи)
        console_level: Уровень логирования для консоли (по умолчанию WARNING - только важные)

    Returns:
        Кортеж (file_handler, console_handler)
    """
    # Детальный формат для файла (с filename:lineno для отладки)
    file_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    )

    # Упрощенный формат для консоли (без filename:lineno, чтобы не засорять)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Обработчик для записи в файл с ротацией (7 MB, 5 файлов)
    # В файл пишем все логи (INFO и выше)
    max_bytes = 7 * 1024 * 1024  # 7 MB
    backup_count = 5  # Храним 5 ротированных файлов
    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(file_format)

    # Обработчик для консоли
    # В консоль выводим только важные сообщения (WARNING и выше)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_format)

    return file_handler, console_handler


class AdminAlertHandler(logging.Handler):
    """Обработчик логирования для отправки уведомлений администратору при ошибках."""

    def emit(self, record: logging.LogRecord) -> None:
        """Отправляет уведомление администратору при ошибках."""
        global _admin_alert_callback, _last_alert_time, _alert_cooldown

        # Отправляем уведомления только для ERROR и выше
        if record.levelno < logging.ERROR:
            return

        # Проверяем cooldown, чтобы не спамить уведомлениями
        current_time = time.time()
        if current_time - _last_alert_time < _alert_cooldown:
            return

        # Проверяем, есть ли функция для отправки уведомлений
        if _admin_alert_callback is None:
            return

        message = record.getMessage()
        if any(pattern in message for pattern in _alert_ignore_patterns):
            return

        # Обновляем время последнего уведомления
        _last_alert_time = current_time

        # Формируем сообщение об ошибке
        error_message = "🚨 <b>Error in log</b>\n\n"
        error_message += f"<b>Level:</b> {record.levelname}\n"
        error_message += f"<b>Module:</b> {record.name}\n"
        error_message += f"<b>Message:</b> {message}\n"

        # Пытаемся отправить уведомление асинхронно
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_admin_alert_callback(error_message))
        except RuntimeError:
            # Если нет запущенного event loop, просто логируем
            pass


def setup_root_logger(
    log_filename: str = "bot.log",
    file_level: int = logging.INFO,
    console_level: int = logging.WARNING,
    logs_dir: Optional[Path] = None,
) -> None:
    """
    Настраивает корневой логгер для всех модулей.

    Все модули, использующие logging.getLogger(__name__), автоматически
    будут логировать через корневой логгер в указанный файл с ротацией.

    Args:
        log_filename: Имя файла для логов (по умолчанию "bot.log")
        file_level: Уровень логирования для файла (по умолчанию INFO - все логи)
        console_level: Уровень логирования для консоли (по умолчанию WARNING - только важные)
        logs_dir: Директория для логов. Если не указана, используется logs/ в корне проекта

    Example:
        >>> setup_root_logger()
        >>> logger = logging.getLogger(__name__)  # Теперь будет логировать в bot.log
        >>> logger.info("Message")  # Попадет только в файл
        >>> logger.warning("Warning")  # Попадет и в файл, и в консоль
    """
    # Проверяем, не настроен ли уже корневой логгер
    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Логгер уже настроен, ничего не делаем
        return

    # Определяем директорию для логов
    if logs_dir is None:
        logs_dir = Path(__file__).parent.parent / "logs"

    # Создаем папку logs, если её нет
    logs_dir.mkdir(exist_ok=True)

    # Настраиваем корневой логгер
    # Устанавливаем минимальный уровень (INFO), чтобы все логи проходили
    root_logger.setLevel(min(file_level, console_level))

    # Создаем обработчики для корневого логгера с разными уровнями
    log_file = logs_dir / log_filename
    file_handler, console_handler = _create_handlers(
        log_file, file_level, console_level
    )
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Добавляем обработчик для уведомлений администратора (будет настроен позже)
    admin_handler = AdminAlertHandler()
    admin_handler.setLevel(logging.ERROR)
    root_logger.addHandler(admin_handler)


def set_admin_alert_callback(callback):
    """
    Устанавливает функцию обратного вызова для отправки уведомлений администратору.

    Args:
        callback: Асинхронная функция, принимающая сообщение и отправляющая его админу
    """
    global _admin_alert_callback
    _admin_alert_callback = callback
