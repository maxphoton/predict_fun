"""
Router for referral code management (/set_ref_code command).
Handles setting referral code for registered users.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from database import get_user
from predict_api import PredictAPIClient

logger = logging.getLogger(__name__)

# ============================================================================
# States for referral code setting
# ============================================================================


class SetReferralStates(StatesGroup):
    """States for set referral code command."""

    waiting_referral_code = State()


# ============================================================================
# Router and handlers
# ============================================================================

referral_router = Router()


@referral_router.message(Command("set_ref_code"))
async def cmd_set_ref_code(message: Message, state: FSMContext):
    """Обработчик команды /set_ref_code - установка реферального кода."""
    logger.info(f"Команда /set_ref_code от пользователя {message.from_user.id}")

    # Проверяем, зарегистрирован ли пользователь
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(
            """❌ You are not registered. Use /start to register first."""
        )
        return

    await message.answer(
        """📝 <b>Set Referral Code</b>

Please enter a 5-character referral code:

⚠️ <b>Important:</b>
• The code must be exactly 5 characters long
• You can set the referral code only once
• If a code is already set, you cannot change it"""
    )
    await state.set_state(SetReferralStates.waiting_referral_code)


@referral_router.message(SetReferralStates.waiting_referral_code)
async def process_referral_code(message: Message, state: FSMContext):
    """Обработчик ввода реферального кода."""
    referral_code = message.text.strip()

    # Валидация: код должен быть 5 символов
    if len(referral_code) != 5:
        await message.answer(
            """❌ Invalid referral code format.

The referral code must be exactly 5 characters long.

Please enter a valid 5-character code:"""
        )
        return

    telegram_id = message.from_user.id
    logger.info(
        f"Пользователь {telegram_id} пытается установить реферальный код: {referral_code}"
    )

    try:
        # Получаем данные пользователя (пользователь уже проверен на первом шаге)
        user = await get_user(telegram_id)

        # Создаем API клиент
        api_client = PredictAPIClient(
            api_key=user["api_key"],
            wallet_address=user["wallet_address"],
            private_key=user["private_key"],
        )

        # Устанавливаем реферальный код
        success = await api_client.set_referral(referral_code)

        if success:
            await message.answer(
                f"""✅ <b>Referral code set successfully!</b>

Your referral code: <code>{referral_code}</code>

The referral code has been set for your account."""
            )
            logger.info(
                f"Пользователь {telegram_id} успешно установил реферальный код: {referral_code}"
            )
        else:
            await message.answer(
                """❌ <b>Failed to set referral code</b>

Possible reasons:
• The referral code is already set for your account
• The referral code format is invalid
• API error occurred

Please check the code and try again, or contact support if the problem persists."""
            )
            logger.warning(
                f"Не удалось установить реферальный код для пользователя {telegram_id}: {referral_code}"
            )

    except Exception as e:
        logger.error(
            f"Ошибка при установке реферального кода для пользователя {telegram_id}: {e}",
            exc_info=True,
        )
        await message.answer(
            f"""❌ <b>Error setting referral code</b>

An error occurred: {str(e)}

Please try again later or contact support."""
        )

    finally:
        await state.clear()
