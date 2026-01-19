"""
Роутер для административных команд бота.
Содержит все хэндлеры, доступные только администратору.
"""

import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message
from config import settings
from database import (
    delete_user,
    export_all_tables_to_zip,
    get_statistics,
    get_user,
)
from invites import get_invites_statistics, get_unused_invites
from log_utils import get_latest_log_file

logger = logging.getLogger(__name__)

# Создаем роутер для административных команд
admin_router = Router()


# ============================================================================
# States for admin commands
# ============================================================================


class DeleteUserStates(StatesGroup):
    """States for delete user command."""

    waiting_telegram_id = State()


# ============================================================================
# Admin command handlers
# ============================================================================


@admin_router.message(Command("get_db"))
async def cmd_get_db(message: Message):
    """Обработчик команды /get_db - экспорт всех таблиц базы данных в ZIP архив и файлов логов (только для администратора)."""
    logger.info(f"Команда /get_db от пользователя {message.from_user.id}")
    # Проверяем права администратора
    if message.from_user.id != settings.admin_telegram_id:
        return

    try:
        # Экспортируем все таблицы в ZIP архив
        zip_content = await export_all_tables_to_zip()

        # Создаем файл для отправки
        zip_file = BufferedInputFile(zip_content, filename="database_export.zip")

        await message.answer_document(
            document=zip_file, caption="📊 Database export (all tables)"
        )
        logger.info(f"Администратор {message.from_user.id} экспортировал базу данных")

        # Отправляем последний файл лога
        logs_dir = Path(__file__).parent.parent / "logs"
        latest_log = get_latest_log_file(logs_dir)

        if latest_log and latest_log.exists():
            try:
                log_content = latest_log.read_bytes()
                log_file = BufferedInputFile(log_content, filename=latest_log.name)
                await message.answer_document(
                    document=log_file, caption=f"📝 Latest log file: {latest_log.name}"
                )
                logger.info(f"Отправлен последний файл лога: {latest_log.name}")
            except Exception as e:
                logger.error(f"Ошибка при отправке файла лога {latest_log.name}: {e}")
                await message.answer(f"❌ Error sending log file: {e}")
        else:
            logger.warning("Последний файл лога не найден")
            await message.answer("⚠️ Latest log file not found")

    except Exception as e:
        logger.error(f"Ошибка экспорта базы данных: {e}")
        await message.answer(f"""❌ Error exporting database: {e}""")


@admin_router.message(Command("get_invites"))
async def cmd_get_invites(message: Message):
    """Обработчик команды /get_invites - получение неиспользованных инвайтов (только для администратора).

    Использование: /get_invites [количество]
    Если количество не указано, генерируется 10 инвайтов по умолчанию.
    """
    logger.info(f"Команда /get_invites от пользователя {message.from_user.id}")
    # Проверяем права администратора
    if message.from_user.id != settings.admin_telegram_id:
        return

    try:
        # Извлекаем количество инвайтов из аргументов команды
        command_parts = message.text.split()
        invites_count = 10  # Значение по умолчанию

        if len(command_parts) > 1:
            try:
                invites_count = int(command_parts[1])
                if invites_count <= 0:
                    await message.answer(
                        "❌ Invalid number. Please enter a positive number.\n"
                        "Example: /get_invites 5"
                    )
                    return
            except ValueError:
                await message.answer(
                    "❌ Invalid format. Please enter a number.\nExample: /get_invites 5"
                )
                return

        # Получаем статистику
        stats = await get_invites_statistics()

        # Получаем указанное количество неиспользованных инвайтов (создаст новые если нужно)
        invites = await get_unused_invites(invites_count)

        # Формируем сообщение со статистикой и инвайтами
        stats_text = f"""📊 <b>Invites Statistics:</b>
• Total: {stats["total"]}
• Used: {stats["used"]}
• Unused: {stats["unused"]}

📋 <b>{invites_count} Unused Invites (ID - Code):</b>
"""

        invites_list = []
        for invite in invites:
            invites_list.append(f"{invite['id']} - <code>{invite['invite']}</code>")

        invites_text = "\n".join(invites_list)

        full_message = stats_text + invites_text

        await message.answer(full_message)
        logger.info(
            f"Администратор {message.from_user.id} получил список из {invites_count} инвайтов"
        )
    except Exception as e:
        logger.error(f"Ошибка получения инвайтов: {e}")
        await message.answer(f"""❌ Error getting invites: {e}""")


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Обработчик команды /stats - получение статистики по базе данных (только для администратора)."""
    logger.info(f"Команда /stats от пользователя {message.from_user.id}")
    # Проверяем права администратора
    if message.from_user.id != settings.admin_telegram_id:
        return

    try:
        # Получаем статистику из базы данных
        stats = await get_statistics()

        # Получаем статистику по инвайтам
        invites_stats = await get_invites_statistics()

        # Формируем сообщение со статистикой
        message_text = f"""📊 <b>Database Statistics</b>

👥 <b>Users:</b>
• Total users: {stats["users_total"]}
• Users with orders: {stats["users_with_orders"]}
• Users with active orders: {stats["unique_users_with_open_orders"]}

📋 <b>Orders:</b>
• Total orders: {stats["orders_total"]}
• Unique markets: {stats["unique_markets"]}

📈 <b>Orders by Status:</b>"""

        # Добавляем статистику по статусам
        status_emojis = {
            "OPEN": "🟢",
            "FILLED": "✅",
            "CANCELLED": "❌",
            "EXPIRED": "⏰",
            "INVALIDATED": "⚠️",
        }

        orders_by_status = stats["orders_by_status"]
        orders_amount_by_status = stats["orders_amount_by_status"]

        # Сортируем статусы по количеству ордеров (от большего к меньшему)
        sorted_statuses = sorted(
            orders_by_status.items(), key=lambda x: x[1], reverse=True
        )

        for status, count in sorted_statuses:
            emoji = status_emojis.get(status, "📌")
            amount = orders_amount_by_status.get(status, 0.0)
            message_text += f"\n{emoji} {status}: {count} ({amount:.2f} USDT)"

        # Если нет ордеров с каким-то статусом, показываем 0
        all_statuses = ["OPEN", "FILLED", "CANCELLED", "EXPIRED", "INVALIDATED"]
        for status in all_statuses:
            if status not in orders_by_status:
                emoji = status_emojis.get(status, "📌")
                message_text += f"\n{emoji} {status}: 0 (0.00 USDT)"

        # Добавляем общую сумму и среднюю сумму ордера
        message_text += f"""

💰 <b>Total Amount:</b> {stats["orders_total_amount"]:.2f} USDT
📊 <b>Average Order Amount:</b> {stats["orders_avg_amount"]:.2f} USDT

🎫 <b>Invites:</b>
• Total: {invites_stats["total"]}
• Used: {invites_stats["used"]}
• Unused: {invites_stats["unused"]}"""

        await message.answer(message_text)
        logger.info(f"Администратор {message.from_user.id} получил статистику")
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await message.answer(f"""❌ Error getting statistics: {e}""")


@admin_router.message(Command("delete_user"))
async def cmd_delete_user(message: Message, state: FSMContext):
    """Обработчик команды /delete_user - удаление пользователя из БД (только для администратора)."""
    logger.info(f"Команда /delete_user от пользователя {message.from_user.id}")
    # Проверяем права администратора
    if message.from_user.id != settings.admin_telegram_id:
        return

    await message.answer(
        """🗑️ <b>Delete User</b>
Please enter the Telegram ID of the user you want to delete.
The user and all their orders will be removed from the database, allowing them to register again."""
    )
    await state.set_state(DeleteUserStates.waiting_telegram_id)


@admin_router.message(DeleteUserStates.waiting_telegram_id)
async def process_delete_user_telegram_id(message: Message, state: FSMContext):
    """Обработчик ввода Telegram ID для удаления пользователя."""
    # Проверяем права администратора
    if message.from_user.id != settings.admin_telegram_id:
        await state.clear()
        return

    try:
        # Пытаемся преобразовать введенный текст в число
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            """❌ Invalid Telegram ID format. Please enter a numeric ID.
Example: 123456789

Please try again:"""
        )
        return

    # Проверяем, существует ли пользователь
    user = await get_user(telegram_id)
    if not user:
        await message.answer(
            f"""❌ User with Telegram ID <code>{telegram_id}</code> not found in database.
Please check the ID and try again:"""
        )
        await state.clear()
        return

    # Удаляем пользователя
    try:
        deleted = await delete_user(telegram_id)
        if deleted:
            username = user.get("username", "N/A")
            await message.answer(
                f"""✅ User deleted successfully!

📋 <b>Deleted User Info:</b>
• Telegram ID: <code>{telegram_id}</code>
• Username: @{username if username != "N/A" else "N/A"}

The user and all their orders have been removed from the database.
They can now register again using /start."""
            )
            logger.info(
                f"Администратор {message.from_user.id} удалил пользователя {telegram_id}"
            )
        else:
            await message.answer(
                f"""❌ Failed to delete user with Telegram ID <code>{telegram_id}</code>.
Please try again:"""
            )
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя {telegram_id}: {e}")
        await message.answer(
            f"""❌ Error deleting user: {e}
Please try again:"""
        )
    finally:
        await state.clear()
