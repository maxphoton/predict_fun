"""
Router for proxy management (/set_proxy command).
Handles proxy update process with format validation and connection check.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from database import get_user, update_proxy
from proxy_checker import check_proxy_health, validate_proxy_format

logger = logging.getLogger(__name__)

# ============================================================================
# States for proxy update
# ============================================================================


class ProxyStates(StatesGroup):
    """States for the proxy update process."""

    waiting_proxy = State()


# ============================================================================
# Router and handlers
# ============================================================================

proxy_router = Router()


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Creates inline keyboard with cancel button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖️ Отменить", callback_data="cancel_proxy")]
        ]
    )


@proxy_router.message(Command("set_proxy"))
async def cmd_set_proxy(message: Message, state: FSMContext):
    """Handler for /set_proxy command - start of proxy update process."""
    logger.info(f"Команда /set_proxy от пользователя {message.from_user.id}")

    # Проверяем, зарегистрирован ли пользователь
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(
            """✖️ You are not registered. Use /start to register first."""
        )
        return

    # Запрашиваем прокси с кнопкой отмены
    await message.answer(
        """🔐 Please enter your proxy server for secure connection to Predict.

Proxy format: ip:port:login:password

Example: 192.168.1.1:8080:user:pass""",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(ProxyStates.waiting_proxy)


@proxy_router.message(ProxyStates.waiting_proxy)
async def process_proxy(message: Message, state: FSMContext):
    """Handles proxy input and performs all checks before updating."""
    telegram_id = message.from_user.id

    # Валидируем формат прокси
    proxy_input = message.text.strip() if message.text else ""
    is_valid, error_message = validate_proxy_format(proxy_input)

    if not is_valid:
        error_text = (
            f"✖️ Invalid proxy format: {error_message}"
            if proxy_input
            else "✖️ Please enter your proxy server."
        )
        await message.answer(
            f"""{error_text}

Proxy format: ip:port:login:password

Example: 192.168.1.1:8080:user:pass""",
            reply_markup=get_cancel_keyboard(),
        )
        return

    # Проверяем прокси
    await message.answer("""🔍 Checking proxy connection...""")

    try:
        proxy_status = await check_proxy_health(proxy_input)
        if proxy_status != "working":
            await message.answer(
                """✖️ Proxy check failed. The proxy is not working.

Please enter a valid proxy server.

Proxy format: ip:port:login:password

Example: 192.168.1.1:8080:user:pass""",
                reply_markup=get_cancel_keyboard(),
            )
            return
    except Exception as e:
        logger.error(f"Ошибка проверки прокси для пользователя {telegram_id}: {e}")
        await message.answer(
            """✖️ Error checking proxy.

Please enter a valid proxy server.

Proxy format: ip:port:login:password

Example: 192.168.1.1:8080:user:pass""",
            reply_markup=get_cancel_keyboard(),
        )
        return

    # Прокси проверен успешно, обновляем в БД
    try:
        await update_proxy(telegram_id, proxy_input, proxy_status)

        # Удаляем сообщение пользователя с прокси
        try:
            await message.delete()
        except Exception:
            pass

        await state.clear()
        await message.answer(
            """✅ Proxy updated successfully!

Your proxy has been verified and saved.

Use the /check_account command to verify your proxy status."""
        )
        logger.info(f"Прокси для пользователя {telegram_id} успешно обновлен")

    except Exception as e:
        logger.error(f"Ошибка обновления прокси для пользователя {telegram_id}: {e}")
        await message.answer(
            """✖️ Error updating proxy.

Please try again later or contact support via /support."""
        )
        await state.clear()


@proxy_router.callback_query(F.data == "cancel_proxy")
async def cancel_proxy_handler(callback: CallbackQuery, state: FSMContext):
    """Handler for cancel button - exits proxy update process."""
    current_state = await state.get_state()
    if current_state is None:
        await callback.answer("Нет активного процесса для отмены.")
        return

    await state.clear()
    await callback.message.edit_text("✖️ Процесс настройки прокси отменен.")
    await callback.answer("Отменено")
    logger.info(f"Пользователь {callback.from_user.id} отменил настройку прокси")
