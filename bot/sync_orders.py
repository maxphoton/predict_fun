"""
Script for automatic order synchronization and repositioning.
Maintains a constant offset (in ticks) between the current market price and the order's target price.

PROCESS OVERVIEW:
================

1. MAIN LOOP (async_sync_all_orders):
   - Retrieves all users from the database
   - For each user, processes their active orders sequentially
   - Outputs final statistics (cancelled, placed, errors)
   - Each user is processed independently with their own API client

2. ORDER STATUS CHECK (process_user_orders):
   For each active order from database:
   a. Checks order status via API (get_order_by_id):
      - Compares database status ('OPEN') with API status
      - If status changed from 'OPEN' to 'FILLED':
        * Updates database status to 'FILLED'
        * Sends notification to user with order details from API (price, market link, etc.)
        * Skips further processing (order is no longer active)
      - If status changed from 'OPEN' to 'CANCELLED', 'EXPIRED', or 'INVALIDATED':
        * Updates database status to the API status (CANCELLED, EXPIRED, or INVALIDATED)
        * Skips further processing (no notification sent for canceled/expired/invalidated orders)
      - If status check fails, continues with normal processing (graceful degradation)

3. ORDER PROCESSING (process_user_orders):
   For each active order (after status check):
   a. Gets current market price from orderbook:
      - For BUY orders: uses best_bid (highest bid price)
      - For SELL orders: uses best_bid (highest bid price)
      - When price goes UP: best_bid increases → SELL order gets closer to execution
      - When price goes DOWN: best_bid decreases → BUY order gets closer to execution
   b. Calculates new target price using saved offset_ticks from database:
      - BUY: new_target_price = current_price - (offset_ticks * TICK_SIZE)
      - SELL: new_target_price = current_price + (offset_ticks * TICK_SIZE)
      - Price is clamped to [0.001, 0.999] range (API requirement)
   c. Calculates target price change in cents:
      target_price_change_cents = abs(new_target_price - old_target_price) * 100
   d. Checks if change is sufficient using reposition_threshold_cents:
      * If change >= threshold: adds order_id to cancellation list AND new order params to placement list
        (both lists updated simultaneously to maintain consistency)
      * If change < threshold: skips repositioning (saves API calls and gas fees)
   e. Adds price change notification to list ONLY if order will be repositioned

4. NOTIFICATIONS (sent immediately after order processing):
   - Price change notifications are sent ONLY for orders that will be repositioned
   - Each notification indicates that the order will be repositioned
   - Includes: old/new current prices, old/new target prices, price change in cents,
     target price change in cents, offset, reposition threshold
   - Notifications sent BEFORE cancellation/placement to inform user immediately

5. ORDER CANCELLATION:
   - Cancels old orders via API (off-chain, removal from orderbook)
   - BATCHES ARE FORMED PER USER: all orders for one user are in the same batch
   - Checks success via result['success'] and result['removed'] from API response
   - Logs each cancellation with User ID and Market ID for debugging
   - If ANY order fails to cancel, skips placement for ALL orders (safety check)

6. ORDER PLACEMENT:
   - Places new orders sequentially ONLY if ALL old orders were successfully cancelled
   - BATCHES ARE FORMED PER USER: all orders for one user are in the same batch
   - Uses SDK + REST API: build_and_sign_limit_order + place_order
   - Logs each placement with User ID and Market ID for debugging
   - If placement fails for specific order (e.g., insufficient balance):
     * Sends error notification to user for THAT specific order (not for entire batch)
     * Notification includes old_order_id (cancelled), error code, and error message
     * Other orders in batch continue to be processed

7. DATABASE UPDATE:
   - Updates database ONLY for successfully placed orders
   - Updates: order_id (old hash -> new hash), current_price, target_price
   - Sends success notification to user after database update
   - If placement failed, database is NOT updated (old order remains in DB as cancelled)

KEY FEATURES:
============
- Order status synchronization: Checks order status via API before processing
  * Automatically updates database when orders are filled or cancelled externally
  * Sends notifications for filled orders (with API data: price, market link, etc.)
  * Silently updates cancelled orders without notifications
- Uses offset_ticks from database (does not recalculate delta, preserves original offset)
- Uses reposition_threshold_cents from database (user-configurable per order, default 0.5 cents)
- Skips repositioning when change < threshold (saves API calls and gas fees)
- Sends price change notifications ONLY when order will be repositioned (reduces notification spam)
- Validates cancellation via result['success'] and result['removed']
- Places new orders only if ALL old orders cancelled successfully (safety check)
- Updates database only after successful placement (data consistency)
- Sends error notifications per order if placement fails (user awareness)
- Comprehensive logging with User ID and Market ID for debugging
- Performance monitoring: Logs start time, end time, and duration for each user's processing
- Visual formatting: boxed headers for start/end of sync task
- Runs as background task in bot, synchronizing orders every 60 seconds
- All blocking operations (API calls) are async
- List consistency check: validates that cancellation and placement lists have same length
- Order identification: uses index matching between place_results and orders_to_place to identify failed orders
- Uses status constants (ORDER_STATUS_FILLED, ORDER_STATUS_CANCELLED) for new API

ARCHITECTURE:
============
- async_sync_all_orders(): Main async function used by bot (background task)
  * Logs processing time for each user (start, end, duration)
  * Uses try/except/finally to ensure time logging always happens
- main(): Synchronous function for standalone script execution (legacy, not used in bot)
- process_user_orders(): Processes all orders for one user, returns lists and notifications
  * Checks order status via API before processing (get_order_by_id)
  * Updates database and sends notifications for status changes
  * Calculates price changes and determines if repositioning is needed
- cancel_orders_batch(): Async batch cancellation via API (off-chain)
- place_orders_batch(): Async batch placement via SDK + REST API
- send_price_change_notification(): Sends price change notification to user
- send_order_updated_notification(): Sends success notification after DB update
- send_order_placement_error_notification(): Sends error notification if placement fails
- send_order_filled_notification(): Sends notification when order is filled
  * Uses API order dict (not database dict) for accurate data
  * Includes filled amount, market link, and order details
"""

import asyncio
import time
import traceback
from typing import Dict, List, Optional, Tuple

from config import TICK_SIZE
from database import (
    get_all_users,
    get_user,
    get_user_orders,
    update_order_in_db,
    update_order_status,
)
from logger_config import setup_logger
from predict_api import PredictAPIClient
from predict_api.auth import get_chain_id
from predict_api.sdk_operations import calculate_new_target_price, place_single_order
from predict_sdk import OrderBuilder, OrderBuilderOptions, Side

# Настройка логирования
logger = setup_logger("sync_orders", "sync_orders.log")

# Константы статусов для нового API (соответствуют статусам в API)
ORDER_STATUS_OPEN = "OPEN"
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_CANCELLED = "CANCELLED"
ORDER_STATUS_EXPIRED = "EXPIRED"
ORDER_STATUS_INVALIDATED = "INVALIDATED"


async def get_current_market_price(
    api_client: PredictAPIClient, market_id: int, side: str, token_name: str
) -> Optional[float]:
    """
    Получает текущую цену рынка для рынка.

    Для BUY и SELL используется best_bid (самый высокий бид):
    - BUY: когда цена ВНИЗ (best_bid уменьшается), ордер ближе к исполнению
    - SELL: когда цена ВВЕРХ (best_bid увеличивается), ордер ближе к исполнению

    Args:
        api_client: Клиент Predict.fun API
        market_id: ID рынка
        side: BUY или SELL - для обоих используется best_bid
        token_name: "YES" или "NO" - для определения правильной цены

    Returns:
        Текущая цена или None в случае ошибки
    """
    try:
        orderbook = await api_client.get_orderbook(market_id=market_id)

        if not orderbook:
            logger.error(f"Ошибка получения orderbook для рынка {market_id}")
            return None

        # Новый API возвращает массивы массивов: [[price, size], ...]
        bids = orderbook.get("bids", [])

        # Для BUY и SELL используем best_bid (самый высокий бид)
        # BUY: когда цена ВНИЗ (best_bid уменьшается), ордер ближе к исполнению
        # SELL: когда цена ВВЕРХ (best_bid увеличивается), ордер ближе к исполнению
        if bids and len(bids) > 0:
            # bids - это массив массивов [[price, size], ...]
            # Берем первый элемент (самый высокий бид) и извлекаем цену
            bid_prices = []
            for bid in bids:
                if isinstance(bid, list) and len(bid) >= 1:
                    try:
                        price = float(bid[0])  # Первый элемент - цена
                        bid_prices.append(price)
                    except (ValueError, TypeError):
                        continue
            if bid_prices:
                best_bid = max(bid_prices)
                # Если это NO токен, цена NO = 1 - price_yes
                if token_name == "NO":
                    return 1.0 - best_bid
                return best_bid

        logger.warning(
            f"Не удалось определить текущую цену для рынка {market_id}, side={side}, token={token_name}"
        )
        return None

    except Exception as e:
        logger.error(f"Ошибка при получении текущей цены для рынка {market_id}: {e}")
        return None


async def process_user_orders(
    telegram_id: int, api_client: PredictAPIClient, bot=None
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Обрабатывает ордера пользователя и возвращает списки для отмены и размещения.

    Args:
        telegram_id: ID пользователя в Telegram
        api_client: Клиент Predict.fun API (уже создан)
        bot: Экземпляр aiogram Bot для отправки уведомлений (опционально)

    Returns:
        Tuple: (список order_api_id для отмены, список параметров новых ордеров, список уведомлений о смещении цены)
        orders_to_cancel: [order_api_id: str, ...] - список ID ордеров для отмены
        orders_to_place: [{'old_order_hash': str, 'old_order_api_id': str, 'market_slug': str, ...}, ...]
        price_change_notifications: [{'order_hash': str, 'order_api_id': str, 'market_slug': str, ...}, ...]
    """
    orders_to_cancel = []  # Список order_api_id для отмены
    orders_to_place = []
    price_change_notifications = []  # Список уведомлений о смещении цены

    # Получаем активные ордера из БД (статус OPEN соответствует активным ордерам)
    db_orders = await get_user_orders(telegram_id, status=ORDER_STATUS_OPEN)

    if not db_orders:
        logger.info(f"У пользователя {telegram_id} нет активных ордеров")
        return orders_to_cancel, orders_to_place, price_change_notifications

    logger.info(
        f"Обработка {len(db_orders)} активных ордеров для пользователя {telegram_id}"
    )

    # Обрабатываем каждый ордер
    for db_order in db_orders:
        try:
            order_hash = db_order.get("order_hash")
            market_id = db_order.get("market_id")
            market_title = db_order.get("market_title")
            market_slug = db_order.get("market_slug")
            token_id = db_order.get("token_id")  # Используем token_id из БД
            token_name = db_order.get("token_name")  # YES или NO
            side = db_order.get("side")  # BUY или SELL
            current_price_at_creation = db_order.get("current_price", 0.0)
            target_price = db_order.get("target_price", 0.0)
            offset_ticks = db_order.get("offset_ticks", 0)
            amount = db_order.get("amount", 0.0)
            reposition_threshold_cents = float(
                db_order.get("reposition_threshold_cents")
            )
            db_status = db_order.get("status")
            order_api_id = db_order.get("order_api_id")

            if not order_hash or not market_id or not side or not token_id:
                logger.warning(f"Пропуск ордера с неполными данными: {order_hash}")
                continue

            logger.info(f"--- Обрабатываем ордер {order_hash} со статусом {db_status}")

            # Проверяем статус ордера через API
            # Если ордер был активным, а стал заполненным/отмененным/истекшим/инвалидированным, обновляем БД
            # В новом API order_hash в БД - это hash ордера
            try:
                api_order = await api_client.get_order_by_id(order_hash=order_hash)
                if api_order:
                    # Получаем статус из API (новый API возвращает строки: 'OPEN', 'FILLED', 'CANCELLED', 'EXPIRED', 'INVALIDATED')
                    api_status = api_order.get("status", "").upper()

                    logger.info(
                        f"Ордер {order_hash} статус в API: {api_status} статус в БД: {db_status}"
                    )

                    # Если статус в БД был 'OPEN', а в API стал 'FILLED'
                    if (
                        db_status == ORDER_STATUS_OPEN
                        and api_status == ORDER_STATUS_FILLED
                    ):
                        logger.info(
                            f"Ордер {order_hash} был OPEN, теперь FILLED. Обновляем БД и отправляем уведомление."
                        )

                        # Обновляем статус в БД (используем статус из API напрямую)
                        await update_order_status(order_hash, ORDER_STATUS_FILLED)

                        # Отправляем уведомление пользователю
                        # Используем db_order для базовых данных и api_order для amountFilled (точное значение исполненной суммы)
                        if bot:
                            await send_order_filled_notification(
                                bot, telegram_id, db_order, api_order
                            )

                        # Пропускаем дальнейшую обработку этого ордера
                        continue

                    # Если статус в БД был 'OPEN', а в API стал 'CANCELLED', 'EXPIRED' или 'INVALIDATED'
                    elif db_status == ORDER_STATUS_OPEN and api_status in (
                        ORDER_STATUS_CANCELLED,
                        ORDER_STATUS_EXPIRED,
                        ORDER_STATUS_INVALIDATED,
                    ):
                        logger.info(
                            f"Ордер {order_hash} был OPEN, теперь {api_status}. Обновляем БД."
                        )

                        # Обновляем статус в БД (используем статус из API напрямую)
                        await update_order_status(order_hash, api_status)

                        # Пропускаем дальнейшую обработку этого ордера
                        continue

                    # Если статус изменился, но не попал в известные случаи (неизвестный статус или неожиданное изменение)
                    elif db_status != api_status:
                        # Проверяем, является ли статус известным
                        known_statuses = (
                            ORDER_STATUS_OPEN,
                            ORDER_STATUS_FILLED,
                            ORDER_STATUS_CANCELLED,
                            ORDER_STATUS_EXPIRED,
                            ORDER_STATUS_INVALIDATED,
                        )

                        if api_status not in known_statuses:
                            # Неизвестный статус из API
                            logger.warning(
                                f"⚠️ Неизвестный статус ордера {order_hash} из API: '{api_status}' "
                                f"(был в БД: '{db_status}'). Сохраняем статус в БД как есть."
                            )
                        else:
                            # Известный статус, но неожиданное изменение (например, FILLED -> CANCELLED)
                            logger.warning(
                                f"⚠️ Неожиданное изменение статуса ордера {order_hash}: "
                                f"'{db_status}' -> '{api_status}'. Обновляем БД."
                            )

                        # Обновляем статус в БД (сохраняем статус из API, даже если он неизвестный)
                        await update_order_status(order_hash, api_status)

                        # Пропускаем дальнейшую обработку этого ордера
                        continue
            except Exception as e:
                # Логируем ошибку
                error_str = str(e)
                is_timeout = (
                    "504" in error_str
                    or "Gateway Time-out" in error_str
                    or "timeout" in error_str.lower()
                )

                if is_timeout:
                    logger.info(
                        f"⏱️ Таймаут API при проверке статуса ордера {order_hash}, продолжаем обработку без проверки статуса"
                    )
                else:
                    logger.warning(
                        f"Ошибка при проверке статуса ордера {order_hash} через API: {e}"
                    )

                # Продолжаем обработку, если не удалось проверить статус (graceful degradation)

            # Получаем текущую цену рынка
            new_current_price = await get_current_market_price(
                api_client, market_id, side, token_name
            )
            if not new_current_price:
                logger.warning(
                    f"Не удалось получить текущую цену для ордера {order_hash}"
                )
                continue

            # Вычисляем новую целевую цену с использованием сохраненного offset_ticks
            new_target_price = calculate_new_target_price(
                new_current_price, side, offset_ticks
            )

            # Вычисляем изменение целевой цены в центах
            target_price_change = abs(new_target_price - target_price)
            target_price_change_cents = target_price_change * 100

            # Проверяем, достаточно ли изменение для перестановки ордера
            will_reposition = target_price_change_cents >= reposition_threshold_cents

            price_change = new_current_price - current_price_at_creation

            # Вычисляем ожидаемую целевую цену для старой текущей цены (для проверки)
            expected_old_target_price = calculate_new_target_price(
                current_price_at_creation, side, offset_ticks, TICK_SIZE
            )

            logger.info(f"Цена изменилась для ордера {order_hash}:")
            logger.info(f"  👤 User ID: {telegram_id}")
            logger.info(f"  📊 Market ID: {market_id}")
            logger.info(f"  📊 Market Slug: {market_slug}")
            logger.info(f"  🪙 Token: {token_name} {side}")
            logger.info(f"  Старая текущая цена: {current_price_at_creation}")
            logger.info(f"  Новая текущая цена: {new_current_price}")
            logger.info(f"  Изменение текущей цены: {price_change:+.6f}")
            logger.info(f"  Старая целевая цена (из БД): {target_price}")
            logger.info(
                f"  Ожидаемая целевая цена (расчет): {expected_old_target_price:.6f}"
            )
            logger.info(f"  Новая целевая цена: {new_target_price}")
            logger.info(
                f"  Изменение целевой цены: {target_price_change:.6f} ({target_price_change_cents:.2f}¢)"
            )
            logger.info(f"  Порог перестановки: {reposition_threshold_cents:.2f}¢")
            logger.info(f"  Offset (ticks): {offset_ticks}")
            logger.info(f"  Будет переставлен: {'Да' if will_reposition else 'Нет'}")

            # Добавляем ордер в списки для отмены/размещения только если изменение достаточно
            # ВАЖНО: Ордер добавляется в ОБА списка одновременно, чтобы гарантировать:
            # 1. Каждый отмененный ордер имеет соответствующий новый ордер для размещения
            # 2. Списки всегда одинаковой длины (проверяется позже для безопасности)
            # 3. Невозможно отменить ордер без размещения нового (и наоборот)
            if will_reposition:
                orders_to_cancel.append(order_api_id)
                logger.info(
                    f"✅ Ордер {order_hash} (API ID: {order_api_id}, User: {telegram_id}, Market: {market_id}) добавлен в список для отмены"
                )

                # Подготавливаем параметры нового ордера
                order_side = Side.BUY if side == "BUY" else Side.SELL

                new_order_params = {
                    "old_order_hash": order_hash,  # Старый order_hash для обновления БД
                    "old_order_api_id": order_api_id,  # Старый order_api_id для отмены
                    "market_id": market_id,
                    "market_title": market_title,  # Добавляем title для уведомлений
                    "market_slug": market_slug,  # Добавляем slug для уведомлений
                    "token_id": token_id,
                    "token_name": token_name,  # Добавляем для уведомлений и пересчета цены
                    "side": order_side,  # Side.BUY или Side.SELL из predict_sdk
                    "side_str": side,  # "BUY" или "SELL" (строка) для пересчета цены
                    "offset_ticks": offset_ticks,  # Для пересчета цены перед размещением
                    "price": new_target_price,  # Цена будет пересчитана перед размещением
                    "amount": amount,
                    "current_price_at_creation": new_current_price,  # Сохраняем для обновления БД
                    "target_price": new_target_price,  # Сохраняем для обновления БД (будет пересчитана)
                    "telegram_id": telegram_id,  # Добавляем для логирования
                }

                # Добавляем в список для размещения (всегда в паре с отменой)
                orders_to_place.append(new_order_params)
                logger.info(
                    f"✅ Ордер {order_hash} (User: {telegram_id}, Market: {market_slug}) добавлен в список для размещения"
                )
            else:
                logger.info(
                    f"⏭️ Ордер {order_hash} (User: {telegram_id}, Market: {market_slug}) не будет переставлен: "
                    f"изменение целевой цены недостаточно ({target_price_change_cents:.2f}¢ < {reposition_threshold_cents:.2f}¢)"
                )

            # Добавляем уведомление о смещении цены ТОЛЬКО если ордер будет переставлен
            # Уведомление отправляется только когда изменение достаточно для перестановки
            if will_reposition:
                # Добавляем уведомление о смещении цены только для ордеров, которые будут переставлены
                price_change_notifications.append(
                    {
                        "order_hash": order_hash,
                        "order_api_id": order_api_id,
                        "market_id": market_id,
                        "market_title": market_title,  # Добавляем title для уведомлений
                        "market_slug": market_slug,
                        "token_name": token_name,
                        "side": side,
                        "old_current_price": current_price_at_creation,
                        "new_current_price": new_current_price,
                        "old_target_price": target_price,
                        "new_target_price": new_target_price,
                        "price_change": price_change,
                        "target_price_change": target_price_change,
                        "target_price_change_cents": target_price_change_cents,
                        "reposition_threshold_cents": reposition_threshold_cents,
                        "offset_ticks": offset_ticks,
                        "will_reposition": will_reposition,
                    }
                )
            else:
                logger.info(
                    f"⏭️ Ордер {order_hash} не будет переставлен, уведомление не отправляется"
                )

        except Exception as e:
            logger.error(
                f"Ошибка при обработке ордера {db_order.get('order_hash', 'unknown')}: {e}"
            )
            # При ошибке не добавляем уведомление, чтобы не вводить пользователя в заблуждение
            continue

    return orders_to_cancel, orders_to_place, price_change_notifications


async def cancel_orders_batch(
    api_client: PredictAPIClient, orders_to_cancel: List[str]
) -> Dict:
    """
    Отменяет ордера через API (off-chain, удаление из orderbook).

    Args:
        api_client: Клиент Predict.fun API
        orders_to_cancel: Список order_api_id для отмены [order_api_id: str, ...]

    Returns:
        Словарь с результатом: {
            'success': bool,
            'removed': List[str],  # ID ордеров, которые были успешно удалены
            'noop': List[str],     # ID ордеров, которые уже были удалены/исполнены/отменены
            'cause': Optional[str] # Причина ошибки, если success=False
        }
    """
    try:
        if not orders_to_cancel:
            logger.warning("Нет ордеров для отмены (не удалось получить ID)")
            return {
                "success": False,
                "removed": [],
                "noop": [],
                "cause": "No orders to cancel",
            }

        # Отменяем ордера через API (off-chain)
        result = await api_client.cancel_orders(order_ids=orders_to_cancel)

        if result.get("success", False):
            removed_count = len(result.get("removed", []))
            noop_count = len(result.get("noop", []))
            logger.info(
                f"Успешно отменено {removed_count} ордеров через API (noop: {noop_count})"
            )
        else:
            logger.error("Ошибка при отмене ордеров через API")

        return result

    except Exception as e:
        logger.error(f"Ошибка при batch отмене ордеров: {e}")
        return {"success": False, "removed": [], "noop": [], "cause": str(e)}


async def place_orders_batch(
    api_client: PredictAPIClient, orders_params: List[Dict]
) -> List[Dict]:
    """
    Размещает ордера через новый API (SDK + REST API).

    В новом API нет батч размещения, поэтому размещаем ордера последовательно.

    Args:
        api_client: Клиент Predict.fun API
        orders_params: Список параметров ордеров (должен содержать order_builder, api_client, market_id, token_id, side, price, amount)

    Returns:
        Список результатов размещения. Каждый результат имеет структуру:
        {
            'success': bool,
            'order_hash': Optional[str],  # Hash ордера (используется как order_id в БД)
            'order_id': Optional[str],    # ID ордера из API (bigint string)
            'error': Optional[str]
        }
    """
    results = []

    for i, params in enumerate(orders_params):
        try:
            order_builder = params.get("order_builder")
            if not order_builder:
                logger.error(f"Отсутствует order_builder в параметрах ордера {i}")
                results.append(
                    {
                        "success": False,
                        "order_hash": None,
                        "order_api_id": None,
                        "error": "Missing order_builder",
                    }
                )
                continue

            # Получаем параметры для размещения
            market_id = params.get("market_id")
            token_id = params.get("token_id")
            side = params.get("side")  # Side.BUY или Side.SELL
            price = float(params["price"])
            amount = float(params["amount"])

            # Проверяем тип side
            if not isinstance(side, Side):
                logger.error(f"Неверный тип side для ордера {i}: {type(side)}")
                results.append(
                    {
                        "success": False,
                        "order_hash": None,
                        "order_api_id": None,
                        "error": "Invalid side type",
                    }
                )
                continue

            # Пересчитываем цену перед размещением (цена могла измениться пока мы отменяли старые ордера)
            token_name = params.get("token_name")
            side_str = params.get("side_str")  # "BUY" или "SELL" (строка)
            offset_ticks = params.get("offset_ticks")

            final_price = price
            current_price_for_db = None

            if token_name and side_str and offset_ticks is not None:
                # Получаем актуальную текущую цену рынка
                current_price = await get_current_market_price(
                    api_client, market_id, side_str, token_name
                )
                if current_price:
                    # Пересчитываем целевую цену с актуальной текущей ценой
                    recalculated_price = calculate_new_target_price(
                        current_price, side_str, offset_ticks, TICK_SIZE
                    )
                    logger.info(
                        f"Пересчитана цена перед размещением ордера {i}: "
                        f"старая цена={price}, новая цена={recalculated_price}, "
                        f"текущая цена рынка={current_price}"
                    )
                    final_price = recalculated_price
                    current_price_for_db = current_price
                else:
                    # Если не удалось получить текущую цену, используем цену из params
                    logger.warning(
                        "Не удалось получить текущую цену для пересчета, используем цену из params"
                    )

            # Получаем данные рынка (если нужно)
            market = None
            if market_id:
                try:
                    market = await api_client.get_market(market_id=market_id)
                except Exception as e:
                    logger.warning(f"Не удалось получить данные рынка {market_id}: {e}")

            # Используем общий метод размещения ордера
            success, order_hash, order_api_id, error_msg = await place_single_order(
                api_client=api_client,
                order_builder=order_builder,
                token_id=token_id,
                side=side,
                price=final_price,  # Используем пересчитанную цену
                amount=amount,
                market=market,
                market_id=market_id,
            )

            if success:
                logger.info(f"Размещен ордер: hash={order_hash}, api_id={order_api_id}")
                # Обновляем цены в params для использования при обновлении БД
                if current_price_for_db is not None:
                    params["current_price_at_creation"] = current_price_for_db
                    params["target_price"] = final_price
                results.append(
                    {
                        "success": True,
                        "order_hash": order_hash,
                        "order_api_id": order_api_id,
                        "error": None,
                    }
                )
            else:
                logger.error(f"Ошибка размещения ордера {i}: {error_msg}")
                results.append(
                    {
                        "success": False,
                        "order_hash": None,
                        "order_api_id": None,
                        "error": error_msg,
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка при размещении ордера {i}: {e}")
            traceback.print_exc()
            results.append(
                {
                    "success": False,
                    "order_hash": None,
                    "order_api_id": None,
                    "error": str(e),
                }
            )

    success_count = sum(1 for r in results if r.get("success", False))
    failed_count = len(results) - success_count
    logger.info(f"Размещено ордеров: {success_count}, ошибок: {failed_count}")

    return results


async def send_price_change_notification(bot, telegram_id: int, notification: Dict):
    """Отправляет уведомление пользователю о смещении цены."""
    try:
        old_price_cents = notification["old_current_price"] * 100
        new_price_cents = notification["new_current_price"] * 100
        old_target_cents = notification["old_target_price"] * 100
        new_target_cents = notification["new_target_price"] * 100
        price_change_cents = notification["price_change"] * 100

        # Convert offset_ticks to cents
        offset_ticks = notification["offset_ticks"]
        offset_cents = offset_ticks * TICK_SIZE * 100

        # Get reposition information
        target_price_change_cents = notification.get("target_price_change_cents", 0.0)
        reposition_threshold_cents = float(
            notification.get("reposition_threshold_cents")
        )

        side_emoji = "📈" if notification["side"] == "BUY" else "📉"
        change_sign = "+" if notification["price_change"] > 0 else ""

        # Status message - уведомление отправляется только когда ордер будет переставлен
        status_emoji = "✅"
        status_text = f"Order will be repositioned (change: {target_price_change_cents:.2f} cents &gt;= threshold: {reposition_threshold_cents:.2f} cents)"

        # Экранируем HTML-специальные символы и используем "cents" вместо символа ¢
        message = f"""🔔 <b>Price Change Detected</b>

{side_emoji} <b>{notification["token_name"]} {notification["side"]}</b>
📊 Market title: {notification.get("market_title", "N/A")}

💰 <b>Current Price:</b>
   Old: {old_price_cents:.2f} cents
   New: {new_price_cents:.2f} cents
   Change: {change_sign}{price_change_cents:.2f} cents

🎯 <b>Target Price:</b>
   Old: {old_target_cents:.2f} cents
   New: {new_target_cents:.2f} cents
   Change: {target_price_change_cents:.2f} cents

⚙️ <b>Settings:</b>
   Offset: {offset_cents:.2f} cents
   Reposition threshold: {reposition_threshold_cents:.2f} cents

{status_emoji} <b>Status:</b> {status_text}"""

        await bot.send_message(chat_id=telegram_id, text=message)
        logger.info(
            f"Sent price change notification to user {telegram_id} for order {notification.get('order_hash', 'unknown')}"
        )
    except Exception as e:
        logger.error(
            f"Failed to send price change notification to user {telegram_id}: {e}"
        )


async def send_order_updated_notification(
    bot, telegram_id: int, order_params: Dict, new_order_hash: str
):
    """Отправляет уведомление пользователю об успешном обновлении ордера в БД."""
    try:
        current_price_cents = order_params["current_price_at_creation"] * 100
        target_price_cents = order_params["target_price"] * 100

        side_emoji = "📈" if order_params.get("side") == Side.BUY else "📉"
        side_text = "BUY" if order_params.get("side") == Side.BUY else "SELL"

        # Форматируем сумму
        amount = order_params.get("amount", 0.0)
        amount_display = (
            f"{amount:.6f}".rstrip("0").rstrip(".")
            if isinstance(amount, (int, float))
            else str(amount)
        )

        message = f"""✅ <b>Order Updated Successfully</b>

{side_emoji} <b>{order_params.get("token_name", "N/A")} {side_text}</b>
📊 Market title: {order_params.get("market_title", "N/A")}

🆔 <b>New Order Hash:</b>
<code>{new_order_hash}</code>

💰 <b>Current Price:</b> {current_price_cents:.2f} cents
🎯 <b>Target Price:</b> {target_price_cents:.2f} cents
💵 <b>Amount:</b> {amount_display} USDT

Order has been successfully moved to maintain the offset."""

        await bot.send_message(chat_id=telegram_id, text=message)
        logger.info(
            f"Sent order updated notification to user {telegram_id} for order {new_order_hash}"
        )
    except Exception as e:
        logger.error(
            f"Failed to send order updated notification to user {telegram_id}: {e}"
        )


async def send_order_placement_error_notification(
    bot,
    telegram_id: int,
    order_params: Dict,
    old_order_hash: str,
    errno: int,
    errmsg: str,
):
    """Отправляет уведомление пользователю об ошибке размещения ордера."""
    try:
        # Используем .get() для всех полей с значениями по умолчанию
        target_price = order_params.get("target_price", 0.0)
        target_price_cents = target_price * 100

        side_emoji = "📈" if order_params.get("side") == Side.BUY else "📉"
        side_text = "BUY" if order_params.get("side") == Side.BUY else "SELL"

        # Форматируем сумму
        amount = order_params.get("amount", "N/A")
        if isinstance(amount, (int, float)):
            amount_display = f"{amount:.6f}".rstrip("0").rstrip(".")
        else:
            amount_display = str(amount)

        # Формируем сообщение об ошибке с информацией из API
        error_type = f"Error {errno}"
        error_description = f"Your order was cancelled, but the new order could not be placed.\n\nError details:\n• Error code: {errno}\n• Error message: {errmsg}"

        message = f"""❌ <b>Order Repositioning Failed</b>

{side_emoji} <b>{order_params.get("token_name", "N/A")} {side_text}</b>
📊 Market title: {order_params.get("market_title", "N/A")}

🆔 <b>Cancelled Order Hash:</b>
<code>{old_order_hash}</code>

💰 <b>Target Price:</b> {target_price_cents:.2f} cents
💵 <b>Amount:</b> {amount_display} USDT

⚠️ <b>{error_type}</b>
{error_description}

<b>⚠️ IMPORTANT:</b> Your old order has been cancelled. Please check your balance and place a new order manually if needed."""

        await bot.send_message(chat_id=telegram_id, text=message)
        logger.info(
            f"Sent order placement error notification to user {telegram_id} for order {old_order_hash}"
        )
    except Exception as e:
        logger.error(
            f"Failed to send order placement error notification to user {telegram_id}: {e}"
        )


async def send_order_filled_notification(
    bot, telegram_id: int, db_order: Dict, api_order: Optional[Dict]
):
    """
    Отправляет уведомление пользователю об исполнении ордера.

    Args:
        bot: Экземпляр aiogram Bot
        telegram_id: ID пользователя в Telegram
        db_order: Словарь с данными ордера из БД
        api_order: Словарь с данными ордера из API (опционально, для получения точного amountFilled)
    """
    try:
        # Извлекаем данные из БД
        order_hash = db_order.get("order_hash")
        market_title = db_order.get("market_title")
        market_slug = db_order.get("market_slug")
        side = db_order.get("side")  # BUY или SELL

        # Определяем side и emoji
        side_enum = side.upper()  # BUY или SELL
        side_emoji = "📈" if side_enum == "BUY" else "📉"

        amount_filled = api_order.get("amountFilled")

        # Форматируем amount (конвертируем из wei в USDT)
        try:
            # amountFilled приходит в wei, нужно разделить на 1e18 для получения USDT
            amount_wei = (
                int(amount_filled) if isinstance(amount_filled, str) else amount_filled
            )
            amount_usdt = amount_wei / 1e18
            amount_display = f"{amount_usdt:.6f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError, ZeroDivisionError):
            amount_display = str(amount_filled)

        market_url = f"https://predict.fun/market/{market_slug}"

        message = f"""🚨 <b>Order Filled - Action Required</b>

{side_emoji} <b>{side_enum}</b>
📊 Market title: {market_title}
📋 Market: <a href="{market_url}">View Market</a>

🆔 <b>Order Hash:</b>
<code>{order_hash}</code>

💵 <b>Filled Amount:</b> {amount_display} USDT

Your order has been successfully filled! Please check the market and consider placing new orders. 🎉"""

        await bot.send_message(chat_id=telegram_id, text=message, parse_mode="HTML")
        logger.info(
            f"Отправлено уведомление об исполнении ордера {order_hash} пользователю {telegram_id}"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}")
        logger.error(traceback.format_exc())


async def send_cancellation_error_notification(
    bot, telegram_id: int, failed_orders: List[Dict]
):
    """
    Отправляет уведомление пользователю об ошибке отмены ордеров.

    Args:
        bot: Экземпляр aiogram Bot
        telegram_id: ID пользователя в Telegram
        failed_orders: Список словарей с информацией о неудачных отменах:
            [{"order_hash": str, "market_id": int, "token_name": str, "side": str, "errno": int, "errmsg": str}, ...]
    """
    try:
        if not failed_orders:
            return

        # Формируем список неудачных ордеров
        orders_list = []
        for order_info in failed_orders:
            order_hash = order_info.get("order_hash", "Unknown")
            market_title = order_info.get("market_title", "N/A")
            token_name = order_info.get("token_name", "N/A")
            side = order_info.get("side", "N/A")
            errno = order_info.get("errno", "N/A")
            errmsg = order_info.get("errmsg", "Unknown error")

            orders_list.append(
                f"• Order <code>{order_hash}</code>\n"
                f"  Market title: {market_title}, Token: {token_name} {side}\n"
                f"  Error: {errno} - {errmsg}"
            )

        orders_text = "\n\n".join(orders_list)

        message = f"""❌ <b>Order Cancellation Failed</b>

⚠️ <b>Failed to cancel {len(failed_orders)} order(s)</b>

The following orders could not be cancelled:
{orders_text}

<b>⚠️ IMPORTANT:</b>
• New orders will NOT be placed (safety check)
• Your old orders remain active
• Please check the orders manually and cancel them if needed
• The repositioning will be retried in the next sync cycle"""

        await bot.send_message(chat_id=telegram_id, text=message)
        logger.info(
            f"Sent cancellation error notification to user {telegram_id} for {len(failed_orders)} failed orders"
        )
    except Exception as e:
        logger.error(
            f"Failed to send cancellation error notification to user {telegram_id}: {e}"
        )


async def async_sync_all_orders(bot):
    """
    Асинхронная функция синхронизации ордеров с уведомлениями пользователям.

    Args:
        bot: Экземпляр aiogram Bot для отправки уведомлений
    """
    logger.info("")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 30 + "НАЧАЛО СИНХРОНИЗАЦИИ ОРДЕРОВ" + " " * 30 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("")

    # Получаем всех пользователей
    users = await get_all_users()
    logger.info(f"Найдено пользователей: {len(users)}")

    if not users:
        logger.warning("В базе данных нет пользователей")
        return

    # Общая статистика
    total_cancelled = 0
    total_noop = 0  # Ордера, которые уже были удалены/исполнены/отменены ранее
    total_processed = 0  # Все обработанные ордера (удаленные + noop)
    total_placed = 0
    total_errors = 0

    # Обрабатываем ордера для каждого пользователя
    for telegram_id in users:
        # Засекаем время начала обработки пользователя
        user_start_time = time.time()
        user_start_time_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(user_start_time)
        )

        logger.info(f"\n{'=' * 80}")
        logger.info(f"Обработка пользователя {telegram_id}")
        logger.info(f"⏰ Время начала: {user_start_time_str}")
        logger.info(f"{'=' * 80}")

        try:
            # Получаем данные пользователя и создаем клиент один раз
            user = await get_user(telegram_id)
            if not user:
                logger.warning(f"Пользователь {telegram_id} не найден в БД")
                continue

            # Создаем API клиент и OrderBuilder один раз для пользователя
            try:
                api_client = PredictAPIClient(
                    api_key=user["api_key"],
                    wallet_address=user["wallet_address"],
                    private_key=user["private_key"],
                )

                # Создаем OrderBuilder для SDK операций
                chain_id = get_chain_id()
                order_builder = await asyncio.to_thread(
                    OrderBuilder.make,
                    chain_id,
                    user["private_key"],
                    OrderBuilderOptions(predict_account=user["wallet_address"]),
                )
            except Exception as e:
                logger.error(
                    f"Ошибка создания клиента для пользователя {telegram_id}: {e}"
                )
                total_errors += 1
                continue

            # Получаем списки ордеров для отмены и размещения, а также уведомления
            (
                orders_to_cancel,
                orders_to_place,
                price_change_notifications,
            ) = await process_user_orders(telegram_id, api_client, bot)

            if not orders_to_cancel and not orders_to_place:
                logger.info(f"Нет ордеров для перемещения у пользователя {telegram_id}")
                continue

            # Отправляем уведомления о смещении цены (независимо от успешности отмены/создания)
            for notification in price_change_notifications:
                await send_price_change_notification(bot, telegram_id, notification)

            logger.info(f"Ордеров для отмены: {len(orders_to_cancel)}")
            logger.info(f"Ордеров для размещения: {len(orders_to_place)}")

            # Проверяем, что списки согласованы (должны быть одинаковой длины, если есть ордера для перестановки)
            # Если will_reposition = True, ордер добавляется в ОБА списка одновременно в одном блоке кода,
            # поэтому теоретически несоответствие невозможно. Но эта проверка - защита от багов в логике
            # (например, если в будущем код изменится и ордер будет добавлен только в один список).
            if len(orders_to_cancel) != len(orders_to_place):
                logger.error(
                    f"КРИТИЧЕСКАЯ ОШИБКА: Несоответствие списков! Отмена={len(orders_to_cancel)}, размещение={len(orders_to_place)}"
                )
                logger.error(
                    "Это указывает на ошибку в логике process_user_orders. Пропускаем обработку для безопасности."
                )
                continue

            # Если списки пустые, но есть уведомления - это нормально (изменение недостаточно)
            if not orders_to_cancel:
                logger.info(
                    f"Нет ордеров для перестановки у пользователя {telegram_id} (изменение недостаточно для всех ордеров)"
                )
                continue

            # Отменяем старые ордера
            cancelled_count = 0
            total_processed = 0  # Инициализируем для использования после блока if
            if orders_to_cancel:
                logger.info(f"🔄 Отмена ордеров для пользователя {telegram_id}...")
                cancel_result = await cancel_orders_batch(api_client, orders_to_cancel)

                # Проверяем успешность отмены
                # cancel_orders возвращает {'success': bool, 'removed': [...], 'noop': [...]}
                if cancel_result.get("success", False):
                    removed = cancel_result.get("removed", [])
                    noop = cancel_result.get("noop", [])
                    cancelled_count = len(removed)
                    user_total_processed = (
                        len(removed) + len(noop)
                    )  # Все обработанные ордера для этого пользователя (удаленные + уже удаленные)
                    logger.info(
                        f"✅ Успешно отменено {cancelled_count} ордеров через API (noop: {len(noop)}, всего обработано: {user_total_processed})"
                    )

                    # Если не все ордера были обработаны (ни в removed, ни в noop), это ошибка
                    if user_total_processed == 0:
                        logger.error(
                            "❌ Не удалось обработать ни одного ордера (ни удалить, ни найти в noop)"
                        )
                        failed_cancellations = []
                        for i, order_api_id in enumerate(orders_to_cancel):
                            order_params = orders_to_place[i]
                            order_hash = order_params.get("old_order_hash", "Unknown")
                            failed_cancellations.append(
                                {
                                    "order_hash": order_hash,
                                    "market_id": order_params.get("market_id", "N/A"),
                                    "market_title": order_params.get(
                                        "market_title", "N/A"
                                    ),
                                    "token_name": order_params.get("token_name", "N/A"),
                                    "side": "BUY"
                                    if order_params.get("side") == Side.BUY
                                    else "SELL",
                                    "errno": "N/A",
                                    "errmsg": "Failed to cancel order",
                                }
                            )
                        await send_cancellation_error_notification(
                            bot, telegram_id, failed_cancellations
                        )
                        continue
                else:
                    # Если отмена не удалась, собираем информацию об ошибке
                    failed_cancellations = []
                    cause = cancel_result.get("cause", "Unknown error")
                    logger.error(f"❌ Ошибка при отмене ордеров: {cause}")

                    # Для каждого ордера создаем запись об ошибке
                    for i, order_api_id in enumerate(orders_to_cancel):
                        order_params = orders_to_place[i]
                        order_hash = order_params.get("old_order_hash", "Unknown")
                        failed_cancellations.append(
                            {
                                "order_hash": order_hash,
                                "market_id": order_params.get("market_id", "N/A"),
                                "market_title": order_params.get("market_title", "N/A"),
                                "token_name": order_params.get("token_name", "N/A"),
                                "side": "BUY"
                                if order_params.get("side") == Side.BUY
                                else "SELL",
                                "errno": "N/A",
                                "errmsg": cause,
                            }
                        )

                    # Отправляем уведомление пользователю об ошибке отмены
                    await send_cancellation_error_notification(
                        bot, telegram_id, failed_cancellations
                    )
                    continue

                # Обновляем общую статистику
                total_cancelled += cancelled_count
                total_noop += len(noop)
                # Используем уже вычисленное значение user_total_processed для обновления глобальной статистики
                total_processed += user_total_processed

                # Проверяем, что все ордера были обработаны (либо удалены, либо уже были удалены ранее)
                # user_total_processed = removed + noop (все ордера, которые были обработаны для этого пользователя)
                if user_total_processed < len(orders_to_cancel):
                    failed_count = len(orders_to_cancel) - user_total_processed
                    logger.warning(
                        f"Не все ордера были обработаны: обработано {user_total_processed} из {len(orders_to_cancel)} "
                        f"(удалено: {cancelled_count}, уже удалены: {len(noop)}, не обработано: {failed_count})"
                    )
                    # Не продолжаем размещение, так как не все ордера были обработаны
                else:
                    # Все ордера обработаны (удалены или уже были удалены ранее)
                    logger.info(
                        f"✅ Все ордера обработаны: удалено {cancelled_count}, уже удалены {len(noop)}"
                    )

            # Размещаем новые ордера только если все старые успешно обработаны
            # (либо удалены через API, либо уже были удалены ранее и попали в noop)
            # БАТЧИ ФОРМИРУЮТСЯ ПО ПОЛЬЗОВАТЕЛЮ: каждый пользователь обрабатывается отдельно,
            # и для каждого пользователя создается свой батч ордеров (все ордера одного пользователя в одном батче)
            if orders_to_place and user_total_processed == len(orders_to_cancel):
                logger.info(f"📝 Размещение ордеров для пользователя {telegram_id}...")
                # Добавляем order_builder и api_client в параметры каждого ордера
                for order_params in orders_to_place:
                    order_params["order_builder"] = order_builder
                    order_params["api_client"] = api_client
                place_results = await place_orders_batch(api_client, orders_to_place)

                # Подсчитываем успешно размещенные ордера для общей статистики
                placed_count = sum(1 for r in place_results if r.get("success", False))
                total_placed += placed_count

                # Обновляем цены в БД для успешно размещенных ордеров и отправляем уведомления
                # Также обрабатываем ошибки размещения
                # ВАЖНО: Уведомления об ошибках отправляются для КАЖДОГО ордера отдельно,
                # если его размещение не удалось (не для всего батча целиком)
                # Индекс i в place_results соответствует индексу i в orders_to_place (гарантировано)
                for i, result in enumerate(place_results):
                    order_params = orders_to_place[
                        i
                    ]  # Берем параметры ордера по индексу
                    old_order_hash = order_params.get(
                        "old_order_hash"
                    )  # Это hash старого ордера, который был отменен

                    is_success = result.get("success", False)

                    if not is_success:
                        # Обрабатываем ошибку размещения для конкретного ордера
                        error = result.get("error", "Unknown error")
                        errno = 0  # В новом API нет errno, используем 0
                        errmsg = error

                        # Отправляем уведомление пользователю об ошибке для ЭТОГО ордера
                        await send_order_placement_error_notification(
                            bot,
                            telegram_id,
                            order_params,
                            old_order_hash,
                            errno,
                            errmsg,
                        )
                        logger.warning(
                            f"Ошибка размещения ордера {old_order_hash} (индекс {i}): {errmsg}"
                        )
                        continue

                    # Успешное размещение
                    new_order_hash = result.get("order_hash")  # Hash нового ордера
                    new_order_api_id = result.get(
                        "order_api_id"
                    )  # ID ордера из API для off-chain отмены

                    if new_order_hash and old_order_hash:
                        # Обновляем ордер в БД
                        await update_order_in_db(
                            old_order_hash,  # Старый hash
                            new_order_hash,  # Новый hash
                            order_params["current_price_at_creation"],
                            order_params["target_price"],
                            new_order_api_id,  # Сохраняем order_api_id для будущих отмен
                        )
                        # Отправляем уведомление об успешном обновлении
                        await send_order_updated_notification(
                            bot, telegram_id, order_params, new_order_hash
                        )

        except Exception as e:
            logger.error(f"Ошибка при обработке пользователя {telegram_id}: {e}")
            total_errors += 1
        finally:
            # Засекаем время окончания обработки пользователя (всегда выполняется)
            user_end_time = time.time()
            user_end_time_str = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(user_end_time)
            )
            user_elapsed = user_end_time - user_start_time

            logger.info(
                f"⏰ Время окончания обработки пользователя {telegram_id}: {user_end_time_str}"
            )
            logger.info(
                f"⏱️  Время обработки пользователя {telegram_id}: {user_elapsed:.2f} секунд ({user_elapsed / 60:.2f} минут)"
            )
            logger.info(f"{'=' * 80}")

    # Итоговая статистика
    logger.info("")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 30 + "ИТОГОВАЯ СТАТИСТИКА" + " " * 30 + "║")
    logger.info("╠" + "=" * 78 + "╣")
    logger.info(f"║ Отменено ордеров (removed): {total_cancelled:<55} ║")
    logger.info(f"║ Уже удалены ранее (noop): {total_noop:<58} ║")
    logger.info(f"║ Всего обработано: {total_processed:<63} ║")
    logger.info(f"║ Размещено ордеров: {total_placed:<62} ║")
    logger.info(f"║ Ошибок: {total_errors:<69} ║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("")
