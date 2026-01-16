"""
Router for market order placement flow (/make_market command).
Handles the complete order placement process from URL input to order confirmation.
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from config import TICK_SIZE
from database import get_user, save_order
from predict_api import PredictAPIClient
from predict_api.auth import get_chain_id
from predict_api.sdk_operations import get_usdt_balance, place_single_order
from predict_sdk import OrderBuilder, OrderBuilderOptions, Side

logger = logging.getLogger(__name__)

# ============================================================================
# States for market order placement
# ============================================================================


class MarketOrderStates(StatesGroup):
    """States for the order placement process."""

    waiting_url = State()
    waiting_submarket = State()  # For market selection from the list
    waiting_side = State()
    waiting_direction = State()
    waiting_amount = State()
    waiting_offset_ticks = State()
    waiting_reposition_threshold = State()  # Порог отклонения для перестановки ордера
    waiting_confirm = State()


# ============================================================================
# Helper functions for market operations
# ============================================================================


def parse_market_url(url: str) -> Optional[str]:
    """
    Parses predict.fun URL and extracts slug.

    Args:
        url: URL вида https://predict.fun/market/metamask-fdv-above-one-day-after-launch

    Returns:
        Slug рынка или None в случае ошибки.
    """
    try:
        parsed = urlparse(url)
        # Извлекаем slug из пути /market/{slug}
        # Пример: https://predict.fun/market/metamask-fdv-above-one-day-after-launch
        path = parsed.path.strip("/")
        if path.startswith("market/"):
            slug = path[7:]  # Убираем 'market/'
            # Убираем слэш в конце на всякий случай
            slug = slug.rstrip("/")
            return slug if slug else None
        return None
    except (ValueError, AttributeError):
        return None


async def get_market_info(api_client: PredictAPIClient, market_id: int):
    """
    Gets market information by market ID.

    Note: Новое API использует один метод get_market() для всех типов рынков
    (категориальные рынки обрабатываются автоматически).
    """
    try:
        market = await api_client.get_market(market_id=market_id)
        return market
    except Exception as e:
        logger.error(f"Error getting market: {e}")
        return None


async def get_markets_by_slug(api_client: PredictAPIClient, slug: str):
    """
    Gets list of markets by slug using get_category endpoint.

    Согласно документации: https://dev.predict.fun/get-category-by-slug-25326911e0
    Метод get_category возвращает категорию с массивом markets.
    Slug в URL - это slug категории, возвращаем список markets из категории.

    Args:
        api_client: PredictAPIClient instance
        slug: Slug категории (например, 'metamask-fdv-above-one-day-after-launch')

    Returns:
        Tuple: (список словарей с данными markets, информация о категории) или (None, None) в случае ошибки.
        Информация о категории: {'title': str или None, 'slug': str}
    """
    try:
        category = await api_client.get_category(slug=slug)
        if not category:
            return None, None

        # Получаем список markets из категории
        markets = category.get("markets", [])
        if not markets:
            return None, None

        # Извлекаем информацию о категории
        category_info = {
            "title": category.get("title"),
            "slug": category.get("slug", slug),
        }

        return markets, category_info
    except Exception as e:
        logger.error(f"Error getting markets by slug {slug}: {e}")
        return None, None


async def get_orderbooks(api_client: PredictAPIClient, market_id: int):
    """
    Gets orderbook for market.

    Note: Новое API возвращает один orderbook для рынка (market_id),
    который содержит цены на основе исхода "Yes".
    Для расчета цены "No": price_no = 1 - price_yes
    """
    try:
        orderbook = await api_client.get_orderbook(market_id=market_id)
        return orderbook
    except Exception as e:
        logger.error(f"Error getting orderbook for market {market_id}: {e}")
        return None


def calculate_spread_and_liquidity(
    orderbook: dict, token_name: str, is_no_token: bool = False
) -> dict:
    """
    Calculates spread and liquidity for a token.

    Args:
        orderbook: Словарь с orderbook из нового API: {'bids': [[price, size], ...], 'asks': [[price, size], ...]}
        token_name: Название токена ("YES" или "NO")
        is_no_token: True если это NO токен (нужно инвертировать цены: price_no = 1 - price_yes)
    """
    if not orderbook:
        return {
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "spread_pct": None,
            "mid_price": None,
            "bid_liquidity": 0,
            "ask_liquidity": 0,
            "total_liquidity": 0,
        }

    # Новое API: orderbook - это словарь с массивами массивов
    bids = orderbook.get("bids", [])  # [[price, size], ...]
    asks = orderbook.get("asks", [])  # [[price, size], ...]

    # Extract best bid (highest price)
    best_bid = None
    if bids and len(bids) > 0:
        bid_prices = [float(bid[0]) for bid in bids]
        if bid_prices:
            best_bid = max(bid_prices)  # Highest bid

    # Extract best ask (lowest price)
    best_ask = None
    if asks and len(asks) > 0:
        ask_prices = [float(ask[0]) for ask in asks]
        if ask_prices:
            best_ask = min(ask_prices)  # Lowest ask

    # Если это NO токен, преобразуем цены из YES в NO
    # Согласно документации: price_no = 1 - price_yes
    # bids для YES (покупка YES) → asks для NO (продажа NO)
    # asks для YES (продажа YES) → bids для NO (покупка NO)
    # Поэтому: best_bid_NO = 1 - best_ask_YES, best_ask_NO = 1 - best_bid_YES
    if is_no_token:
        if best_bid is not None and best_ask is not None:
            best_bid_no = 1.0 - best_ask
            best_ask_no = 1.0 - best_bid
            best_bid = best_bid_no
            best_ask = best_ask_no
        elif best_bid is not None:
            best_ask = 1.0 - best_bid
            best_bid = None
        elif best_ask is not None:
            best_bid = 1.0 - best_ask
            best_ask = None

    spread = None
    spread_pct = None
    mid_price = None

    if best_bid and best_ask:
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2
        spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0

    # Суммируем ликвидность из первых 5 уровней
    bid_liquidity = sum(float(bid[1]) for bid in bids[:5]) if bids else 0
    ask_liquidity = sum(float(ask[1]) for ask in asks[:5]) if asks else 0
    total_liquidity = bid_liquidity + ask_liquidity

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_pct": spread_pct,
        "mid_price": mid_price,
        "bid_liquidity": bid_liquidity,
        "ask_liquidity": ask_liquidity,
        "total_liquidity": total_liquidity,
    }


def calculate_target_price(
    current_price: float, side: str, offset_ticks: int, tick_size: float = TICK_SIZE
) -> Tuple[float, bool]:
    """
    Calculates target price for limit order.

    API requires price range: 0.001 - 0.999 (inclusive)
    """
    MIN_PRICE = 0.001  # Minimum price per API requirements
    MAX_PRICE = 0.999  # Maximum price per API requirements (not 1.0!)

    if side == "BUY":
        target = current_price - offset_ticks * tick_size
    else:  # SELL
        target = current_price + offset_ticks * tick_size

    # Limit to MIN_PRICE - MAX_PRICE range (0.001 - 0.999)
    target = max(MIN_PRICE, min(MAX_PRICE, target))
    is_valid = MIN_PRICE <= target <= MAX_PRICE
    target = round(target, 3)
    # Форматируем и преобразуем обратно в float для гарантии точности (избегаем проблем с float)
    target = float(f"{target:.3f}")

    # Check that after rounding the price is still in valid range
    if target < MIN_PRICE:
        target = MIN_PRICE
        is_valid = True
    elif target > MAX_PRICE:
        target = MAX_PRICE
        is_valid = True

    return target, is_valid


async def check_usdt_balance(
    order_builder: OrderBuilder, required_amount: float
) -> Tuple[bool, float]:
    """
    Checks if USDT balance is sufficient.

    Returns:
        Tuple[bool, float]: (has_sufficient_balance, current_balance_usdt)
    """
    try:
        balance_wei = await get_usdt_balance(order_builder)
        balance_usdt = balance_wei / 1e18

        return balance_usdt >= required_amount, balance_usdt
    except Exception as e:
        logger.error(f"Error checking balance: {e}")
        return False, 0.0


# ============================================================================
# Router and handlers
# ============================================================================

market_router = Router()


@market_router.message(Command("make_market"))
async def cmd_make_market(message: Message, state: FSMContext):
    """Handler for /make_market command - start of order placement process."""
    logger.info(f"Команда /make_market от пользователя {message.from_user.id}")
    user = await get_user(message.from_user.id)

    if not user:
        await message.answer(
            """❌ You are not registered. Use the /start command to register."""
        )
        return

    # Create keyboard with "Cancel" button
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Cancel", callback_data="cancel")

    await message.answer(
        """📊 Place a Limit Order

Please enter the predict.fun market link:""",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(MarketOrderStates.waiting_url)


@market_router.message(MarketOrderStates.waiting_url)
async def process_market_url(message: Message, state: FSMContext):
    """Handles market URL input."""
    url = message.text.strip()
    slug = parse_market_url(url)

    # Get user data and create API client
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(
            """❌ User not found. Please register with /start first."""
        )
        await state.clear()
        return

    # Создаем API клиент и OrderBuilder с обработкой ошибок
    try:
        api_client = PredictAPIClient(
            api_key=user["api_key"],
            wallet_address=user["wallet_address"],
            private_key=user["private_key"],
            proxy_str=user.get("proxy_str"),
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
        # Генерируем код ошибки для сопоставления с логами
        error_str = str(e)
        error_hash = hashlib.md5(error_str.encode()).hexdigest()[:8].upper()
        error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        await message.answer(
            f"""❌ Failed to create API client.

Error code: <code>{error_hash}</code>
Time: {error_time}

Please contact administrator via /support and provide the error code above."""
        )
        await state.clear()
        logger.error(
            f"Ошибка создания клиента для пользователя {message.from_user.id} [CODE: {error_hash}] [TIME: {error_time}]: {e}"
        )
        return

    # Get market information
    await message.answer("""📊 Getting market information...""")

    # Получаем market по slug
    if not slug:
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")
        await message.answer(
            """❌ Failed to extract slug from URL. Please check the URL format.
Expected format: https://predict.fun/market/{slug}""",
            reply_markup=builder.as_markup(),
        )
        await state.clear()
        return

    markets, category_info = await get_markets_by_slug(api_client, slug)

    # Если не получилось получить markets
    if not markets or len(markets) == 0:
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")
        await message.answer(
            """❌ Failed to get markets information. Please check the URL.""",
            reply_markup=builder.as_markup(),
        )
        await state.clear()
        return

    # Всегда показываем список markets для выбора (даже если он один)
    # Build market list for selection
    market_list = []
    for i, market in enumerate(markets, 1):
        if isinstance(market, dict):
            market_id = market.get("id")
            title = market.get("title", f"Market {i}")

            # Извлекаем названия outcomes (токенов) если они есть
            outcomes = market.get("outcomes", [])
            outcome_names = []
            if outcomes:
                for outcome in outcomes:
                    if isinstance(outcome, dict):
                        outcome_name = outcome.get("name")
                        if outcome_name:
                            outcome_names.append(outcome_name)
                    elif isinstance(outcome, str):
                        outcome_names.append(outcome)

            # Формируем текст для кнопки: название рынка + названия токенов
            if outcome_names:
                outcome_text = " / ".join(outcome_names)
                button_text = f"{title} ({outcome_text})"
            else:
                button_text = title
        else:
            logger.warning(f"Market {i} is not a dict: {type(market)}")
            market_id = None
            title = f"Market {i}"
            button_text = title

        market_list.append(
            {
                "id": market_id,
                "title": title,
                "button_text": button_text,
                "data": market,
            }
        )

    # Формируем название категории для сообщения
    if category_info:
        category_title = category_info.get("title")
        category_display = (
            category_title if category_title else category_info.get("slug", slug)
        )
    else:
        category_display = slug

    # Save market list, API client, OrderBuilder and slug to state
    await state.update_data(
        markets=market_list,
        api_client=api_client,
        order_builder=order_builder,
        slug=slug,
    )

    # Create keyboard for market selection
    builder = InlineKeyboardBuilder()
    for i, market_item in enumerate(market_list, 1):
        # Используем button_text который включает названия токенов
        builder.button(
            text=f"{market_item['button_text'][:50]}", callback_data=f"market_{i}"
        )
    builder.button(text="✖️ Cancel", callback_data="cancel")
    builder.adjust(1)

    await message.answer(
        f"""📋 <b>Select Market</b>

Category: <b>{category_display}</b>
Found markets: {len(market_list)}

Select a market:""",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(MarketOrderStates.waiting_submarket)


async def process_market_data(
    message: Message,
    state: FSMContext,
    market: dict,
    market_id: int,
    api_client: PredictAPIClient,
):
    """Processes market data and continues order placement process."""
    # Новое API: получаем один orderbook для рынка
    orderbook = await get_orderbooks(api_client, market_id)

    if not orderbook:
        await message.answer("""❌ Failed to get orderbook for market""")
        await state.clear()
        return

    # Check if orderbook has orders
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])
    has_orders = (bids and len(bids) > 0) or (asks and len(asks) > 0)

    if not has_orders:
        await message.answer(
            """⚠️ <b>Market is inactive</b>

Order books have no orders (bids and asks are empty).
Possible reasons:
• Market has expired or closed
• Market has not started trading yet
• No liquidity on the market"""
        )
        await state.clear()
        return

    # Calculate spread and liquidity
    # Для YES токена используем orderbook как есть
    yes_info = calculate_spread_and_liquidity(orderbook, "YES", is_no_token=False)
    # Для NO токена инвертируем цены (price_no = 1 - price_yes)
    no_info = calculate_spread_and_liquidity(orderbook, "NO", is_no_token=True)

    # Save data to state
    await state.update_data(orderbook=orderbook, yes_info=yes_info, no_info=no_info)

    # Format market information in new format
    market_info_parts = []

    # Information for YES token
    if yes_info["best_bid"] is not None or yes_info["best_ask"] is not None:
        yes_bid = (
            f"{yes_info['best_bid'] * 100:.2f}¢"
            if yes_info["best_bid"] is not None
            else "no"
        )
        yes_ask = (
            f"{yes_info['best_ask'] * 100:.2f}¢"
            if yes_info["best_ask"] is not None
            else "no"
        )
        yes_lines = [f"✅ YES: Bid: {yes_bid} | Ask: {yes_ask}"]

        if yes_info["spread"]:
            spread_line = f"  Spread: {yes_info['spread'] * 100:.2f}¢ ({yes_info['spread_pct']:.2f}%) | Liquidity: ${yes_info['total_liquidity']:,.2f}"
            yes_lines.append(spread_line)
        elif yes_info["total_liquidity"] > 0:
            yes_lines.append(f"  Liquidity: ${yes_info['total_liquidity']:,.2f}")

        market_info_parts.append("\n".join(yes_lines))

    # Information for NO token
    if no_info["best_bid"] is not None or no_info["best_ask"] is not None:
        no_bid = (
            f"{no_info['best_bid'] * 100:.2f}¢"
            if no_info["best_bid"] is not None
            else "no"
        )
        no_ask = (
            f"{no_info['best_ask'] * 100:.2f}¢"
            if no_info["best_ask"] is not None
            else "no"
        )
        no_lines = [f"❌ NO: Bid: {no_bid} | Ask: {no_ask}"]

        if no_info["spread"]:
            spread_line = f"  Spread: {no_info['spread'] * 100:.2f}¢ ({no_info['spread_pct']:.2f}%) | Liquidity: ${no_info['total_liquidity']:,.2f}"
            no_lines.append(spread_line)
        elif no_info["total_liquidity"] > 0:
            no_lines.append(f"  Liquidity: ${no_info['total_liquidity']:,.2f}")

        market_info_parts.append("\n".join(no_lines))

    # Create keyboard with "Cancel" button
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Cancel", callback_data="cancel")

    # Format full message with empty line between blocks
    market_info_text = "\n\n".join(market_info_parts) if market_info_parts else ""

    # Новое API: market - это словарь с полем 'title'
    market_title = market.get("title", "Unknown Market")

    # Create keyboard for side selection
    side_builder = InlineKeyboardBuilder()
    side_builder.button(text="✅ YES", callback_data="side_yes")
    side_builder.button(text="❌ NO", callback_data="side_no")
    side_builder.button(text="✖️ Cancel", callback_data="cancel")
    side_builder.adjust(2)

    await message.answer(
        f"""📋 Market Found: {market_title}

{market_info_text}

📈 Select side:""",
        reply_markup=side_builder.as_markup(),
    )
    await state.set_state(MarketOrderStates.waiting_side)


@market_router.callback_query(
    F.data.startswith("market_"), MarketOrderStates.waiting_submarket
)
async def process_market_selection(callback: CallbackQuery, state: FSMContext):
    """Handles market selection from the list."""
    try:
        market_index = int(callback.data.split("_")[1]) - 1

        data = await state.get_data()
        markets = data.get("markets", [])

        if market_index < 0 or market_index >= len(markets):
            await callback.message.edit_text("""❌ Invalid market selection""")
            await state.clear()
            await callback.answer()
            return

        selected_market_item = markets[market_index]
        market_id = selected_market_item["id"]
        market = selected_market_item["data"]

        if not market_id or not market:
            await callback.message.edit_text("""❌ Failed to determine market ID""")
            await state.clear()
            await callback.answer()
            return

        # Get API client and OrderBuilder from state
        api_client = data.get("api_client")
        order_builder = data.get("order_builder")

        if not api_client or not order_builder:
            await callback.message.edit_text(
                """❌ API client not found. Please start over."""
            )
            await state.clear()
            await callback.answer()
            return

        await callback.message.edit_text(
            f"""📊 Processing market: {selected_market_item["title"]}..."""
        )

        # Новое API: получаем token IDs из outcomes
        outcomes = market.get("outcomes", [])
        if not outcomes or len(outcomes) < 2:
            await callback.message.edit_text("""❌ Failed to determine market tokens""")
            await state.clear()
            await callback.answer()
            return

        # YES токен - первый outcome (index 0), NO токен - второй outcome (index 1)
        yes_token = outcomes[0] if len(outcomes) > 0 else None
        no_token = outcomes[1] if len(outcomes) > 1 else None

        yes_token_id = yes_token.get("onChainId") if yes_token else None
        no_token_id = no_token.get("onChainId") if no_token else None

        if not yes_token_id or not no_token_id:
            await callback.message.edit_text("""❌ Failed to determine market tokens""")
            await state.clear()
            await callback.answer()
            return

        # Save market data to state
        await state.update_data(
            market=market,
            market_id=market_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
        )

        await callback.answer()

        # Continue processing as regular market
        await process_market_data(
            callback.message, state, market, market_id, api_client
        )
    except (ValueError, IndexError, KeyError) as e:
        logger.error(f"Error processing market selection: {e}")
        await callback.message.edit_text("""❌ Error processing market selection""")
        await state.clear()
        await callback.answer()


@market_router.callback_query(
    F.data.startswith("side_"), MarketOrderStates.waiting_side
)
async def process_side(callback: CallbackQuery, state: FSMContext):
    """Handles side selection (YES/NO)."""
    side = callback.data.split("_")[1].upper()

    data = await state.get_data()

    if side == "YES":
        token_id = data["yes_token_id"]
        token_name = "YES"
        current_price = data["yes_info"]["mid_price"]
        is_no_token = False
    else:
        token_id = data["no_token_id"]
        token_name = "NO"
        current_price = data["no_info"]["mid_price"]
        is_no_token = True

    if not current_price:
        await callback.message.answer(
            "❌ Failed to determine current price for selected token"
        )
        await state.clear()
        await callback.answer()
        return

    # Сохраняем только базовые данные о выбранной стороне
    await state.update_data(
        token_id=token_id,
        token_name=token_name,
        current_price=current_price,
        is_no_token=is_no_token,  # Нужен для обработки orderbook в process_amount
    )

    # Create keyboard for direction selection
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 BUY (buy, below current price)", callback_data="dir_buy")
    builder.button(text="📉 SELL (sell, above current price)", callback_data="dir_sell")
    builder.button(text="✖️ Cancel", callback_data="cancel")
    builder.adjust(1)

    await callback.message.edit_text(
        f"""✅ <b>Selected: {token_name}</b>

💵 Current price: {current_price:.6f} ({current_price * 100:.2f}¢)

📈 Select order direction:""",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
    await state.set_state(MarketOrderStates.waiting_direction)


@market_router.callback_query(
    F.data.startswith("dir_"), MarketOrderStates.waiting_direction
)
async def process_direction(callback: CallbackQuery, state: FSMContext):
    """Handles direction selection (BUY/SELL)."""
    direction = callback.data.split("_")[1].upper()

    data = await state.get_data()
    current_price = data["current_price"]
    token_name = data["token_name"]

    # Сохраняем direction
    await state.update_data(
        direction=direction,
        order_side=direction,  # Строка "BUY" или "SELL"
    )

    # Create inline keyboard with Cancel button
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Cancel", callback_data="cancel")

    # Get previous selections
    market = data.get("market", {})
    market_title = market.get("title", "Unknown Market")

    await callback.message.edit_text(
        f"""✅ <b>Selected: {market_title} {direction} {token_name}</b>

💵 Current price: {current_price:.6f} ({current_price * 100:.2f}¢)

💰 Enter the order amount in USDT:""",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
    await state.set_state(MarketOrderStates.waiting_amount)


@market_router.message(MarketOrderStates.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    """Handles amount input after direction selection."""
    try:
        amount = float(message.text.strip())

        if amount <= 0:
            builder = InlineKeyboardBuilder()
            builder.button(text="✖️ Cancel", callback_data="cancel")
            await message.answer(
                """❌ Amount must be a positive number. Please try again:""",
                reply_markup=builder.as_markup(),
            )
            return

        data = await state.get_data()
        order_builder = data.get("order_builder")
        direction = data.get("direction")
        current_price = data.get("current_price")
        token_name = data.get("token_name")
        best_bid = data.get("best_bid")

        if not order_builder:
            await message.answer("""❌ OrderBuilder not found. Please start over.""")
            await state.clear()
            return

        if not direction:
            await message.answer("""❌ Direction not found. Please start over.""")
            await state.clear()
            return

        # Check USDT balance only for BUY orders
        has_balance, balance_usdt = await check_usdt_balance(order_builder, amount)

        if direction == "BUY" and not has_balance:
            builder = InlineKeyboardBuilder()
            builder.button(text="✖️ Cancel", callback_data="cancel")
            await message.answer(
                f"""❌ Insufficient USDT balance to place a BUY order for {amount} USDT.

Your balance: {balance_usdt:.6f} USDT
Required: {amount} USDT

Please enter a smaller amount:""",
                reply_markup=builder.as_markup(),
            )
            return

        await state.update_data(amount=amount)

        # Получаем orderbook здесь, где это действительно нужно (для отображения в сообщении с offset)
        orderbook = data.get("orderbook")
        if not orderbook:
            await message.answer("❌ Failed to get orderbook for selected token")
            await state.clear()
            return

        is_no_token = data.get("is_no_token", False)

        # Новое API: orderbook - это словарь с массивами массивов
        bids_raw = orderbook.get("bids", [])  # [[price, size], ...]
        asks_raw = orderbook.get("asks", [])  # [[price, size], ...]

        # Если это NO токен, инвертируем цены (price_no = 1 - price_yes)
        if is_no_token:
            bids = [[1.0 - float(bid[0]), float(bid[1])] for bid in bids_raw]
            asks = [[1.0 - float(ask[0]), float(ask[1])] for ask in asks_raw]
            # Меняем местами bids и asks для NO (так как инвертировали)
            bids, asks = asks, bids
        else:
            bids = [[float(bid[0]), float(bid[1])] for bid in bids_raw]
            asks = [[float(ask[0]), float(ask[1])] for ask in asks_raw]

        # Sort bids by descending price (highest first)
        sorted_bids = sorted(bids, key=lambda x: x[0], reverse=True) if bids else []

        # Sort asks by ascending price (lowest first)
        sorted_asks = sorted(asks, key=lambda x: x[0]) if asks else []

        # Get best 5 bids (highest prices)
        best_bids = []
        for i, bid_data in enumerate(sorted_bids[:5]):
            price = bid_data[0]
            price_cents = price * 100
            best_bids.append(price_cents)

        # Get best 5 asks (lowest prices)
        best_asks = []
        for i, ask_data in enumerate(sorted_asks[:5]):
            price = ask_data[0]
            price_cents = price * 100
            best_asks.append(price_cents)

        # Find maximum distant bid (lowest of all bids)
        last_bid = None
        if sorted_bids:
            last_bid_price = sorted_bids[-1][0]
            last_bid = last_bid_price * 100

        # Find maximum distant ask (highest of all asks)
        last_ask = None
        if sorted_asks:
            last_ask_price = sorted_asks[-1][0]
            last_ask = last_ask_price * 100

        # Best bid (highest) - first in sorted list
        best_bid = best_bids[0] if best_bids else None

        if not best_bid:
            await message.answer("❌ No bids found in orderbook")
            await state.clear()
            return

        # Format text with best bids
        bids_text = "<b>Best 5 bids:</b>\n"
        for i, bid_price in enumerate(best_bids, 1):
            bids_text += f"{i}. {bid_price:.1f} ¢\n"
        if last_bid and last_bid not in best_bids:
            bids_text += f"...\n{last_bid:.1f} ¢\n"

        # Format text with best asks
        asks_text = "<b>Best 5 asks:</b>\n"
        for i, ask_price in enumerate(best_asks, 1):
            asks_text += f"{i}. {ask_price:.1f} ¢\n"
        if last_ask and last_ask not in best_asks:
            asks_text += f"...\n{last_ask:.1f} ¢\n"

        # Сохраняем best_bid (нужен для дальнейшего использования)
        await state.update_data(best_bid=best_bid)

        # Format balance text
        balance_text = f"\n💰 Your balance: {balance_usdt:.6f} USDT"

        # Create inline keyboard with Cancel button
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")

        # Get previous selections
        token_name_prev = data.get("token_name", token_name)
        direction_prev = data.get("direction", direction)
        market = data.get("market", {})
        market_title = market.get("title", "Unknown Market")

        await message.answer(
            f"""✅ <b>Amount: {amount} USDT</b>{balance_text}

📋 <b>Your selections:</b>
• Market: {market_title}
• Side: {token_name_prev}
• Direction: {direction_prev}

💵 Current price: {current_price:.6f} ({current_price * 100:.2f}¢)

{bids_text}
{asks_text}
⚙️ Set the price offset (in ¢) relative to the best bid ({best_bid:.1f}¢). For example 0.5:

💡 You can select one of the quick options below or enter any other value manually.""",
            reply_markup=builder.as_markup(),
        )

        # Create reply keyboard with quick offset options
        reply_builder = ReplyKeyboardBuilder()
        reply_builder.button(text="0.3")
        reply_builder.button(text="0.6")
        reply_builder.button(text="0.9")
        reply_builder.button(text="1.2")
        reply_builder.button(text="1.5")
        reply_builder.adjust(5)  # All buttons in one row

        await message.answer(
            "Quick options:",
            reply_markup=reply_builder.as_markup(
                resize_keyboard=True, one_time_keyboard=True
            ),
        )
        await state.set_state(MarketOrderStates.waiting_offset_ticks)
    except ValueError:
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")
        await message.answer(
            """❌ Invalid amount format. Enter a number:""",
            reply_markup=builder.as_markup(),
        )


@market_router.message(MarketOrderStates.waiting_offset_ticks)
async def process_offset_ticks(message: Message, state: FSMContext):
    """
    Handles offset input in cents.
    User enters offset in cents, we convert to ticks for validation and further processing.
    """
    try:
        offset_cents = float(message.text.strip())

        data = await state.get_data()
        best_bid = data.get("best_bid")
        current_price = data["current_price"]
        direction = data.get("direction")
        tick_size = TICK_SIZE

        # Вычисляем max_offset_buy и max_offset_sell здесь, где они нужны
        MIN_PRICE = 0.001
        MAX_PRICE = 0.999
        max_offset_buy = int((current_price - MIN_PRICE) / tick_size)
        max_offset_sell = int((MAX_PRICE - current_price) / tick_size)

        if not best_bid:
            await message.answer("❌ Error: best bid not found")
            await state.clear()
            return

        # Convert offset in cents to ticks
        offset_ticks = int(round(offset_cents / (100 * tick_size)))

        # Validation: check value is in valid range
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")

        if offset_ticks < 0:
            await message.answer(
                f"❌ Offset must be at least 0 cents.\n"
                f"Enter a value from 0 to {max(max_offset_buy, max_offset_sell) * tick_size * 100:.1f} cents:",
                reply_markup=builder.as_markup(),
            )
            return

        # Check maximum value (take max of BUY and SELL)
        max_offset = max(max_offset_buy, max_offset_sell)
        max_offset_cents = max_offset * tick_size * 100

        if offset_ticks > max_offset:
            await message.answer(
                f"❌ Offset is too large!\n\n"
                f"• Maximum for BUY: {max_offset_buy * tick_size * 100:.1f} cents\n"
                f"• Maximum for SELL: {max_offset_sell * tick_size * 100:.1f} cents\n\n"
                f"Enter a value from 0 to {max_offset_cents:.1f} cents:",
                reply_markup=builder.as_markup(),
            )
            return

        # Get selected direction
        direction = data.get("direction")
        if not direction:
            await message.answer("❌ Error: direction not found. Please start over.")
            await state.clear()
            return

        # Validate offset for selected direction
        if direction == "BUY" and offset_ticks > max_offset_buy:
            await message.answer(
                f"❌ Offset is too large for BUY!\n\n"
                f"• Maximum for BUY: {max_offset_buy * tick_size * 100:.1f} cents\n\n"
                f"Enter a value from 0 to {max_offset_buy * tick_size * 100:.1f} cents:",
                reply_markup=builder.as_markup(),
            )
            return

        if direction == "SELL" and offset_ticks > max_offset_sell:
            await message.answer(
                f"❌ Offset is too large for SELL!\n\n"
                f"• Maximum for SELL: {max_offset_sell * tick_size * 100:.1f} cents\n\n"
                f"Enter a value from 0 to {max_offset_sell * tick_size * 100:.1f} cents:",
                reply_markup=builder.as_markup(),
            )
            return

        # Calculate target price
        target_price, is_valid = calculate_target_price(
            current_price, direction, offset_ticks, tick_size
        )

        if not is_valid or target_price <= 0:
            await message.answer(
                f"""❌ Error: Calculated price ({target_price:.6f}) is invalid!

Offset {offset_ticks} ticks is too large for current price {current_price:.6f}""",
                reply_markup=builder.as_markup(),
            )
            return

        await state.update_data(offset_ticks=offset_ticks, target_price=target_price)

        # Get previous selections for display
        token_name_prev = data.get("token_name")
        direction_prev = data.get("direction")
        amount_prev = data.get("amount")
        tick_size_prev = data.get("tick_size", TICK_SIZE)
        offset_cents_prev = offset_ticks * tick_size_prev * 100
        market = data.get("market", {})
        market_title = market.get("title", "Unknown Market")

        # Ask for reposition threshold
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")

        await message.answer(
            f"""✅ <b>Offset: {offset_cents_prev:.2f}¢</b>

📋 <b>Your selections:</b>
• Market: {market_title}
• Side: {token_name_prev}
• Direction: {direction_prev}
• Amount: {amount_prev} USDT

⚙️ <b>Reposition Threshold</b>

Enter the price deviation threshold (in cents) for repositioning the order.

For example:
• <code>0.5</code> - reposition when price changes by 0.5 cents or more
• <code>1.0</code> - reposition when price changes by 1 cent or more
• <code>2.0</code> - reposition when price changes by 2 cents or more

Recommended: <code>0.5</code> cents

💡 You can select one of the quick options below or enter any other value manually.

Enter the threshold:""",
            reply_markup=builder.as_markup(),
        )

        # Create reply keyboard with quick threshold options
        reply_builder = ReplyKeyboardBuilder()
        reply_builder.button(text="0.5")
        reply_builder.button(text="1")
        reply_builder.button(text="1.5")
        reply_builder.button(text="2")
        reply_builder.button(text="2.5")
        reply_builder.adjust(5)  # All buttons in one row

        await message.answer(
            "Quick options:",
            reply_markup=reply_builder.as_markup(
                resize_keyboard=True, one_time_keyboard=True
            ),
        )
        await state.set_state(MarketOrderStates.waiting_reposition_threshold)
    except ValueError:
        data = await state.get_data()
        current_price = data.get("current_price", 0)
        tick_size = TICK_SIZE
        MIN_PRICE = 0.001
        MAX_PRICE = 0.999
        max_offset_buy = (
            int((current_price - MIN_PRICE) / tick_size) if current_price > 0 else 0
        )
        max_offset_sell = (
            int((MAX_PRICE - current_price) / tick_size) if current_price > 0 else 0
        )
        max_offset = max(max_offset_buy, max_offset_sell)
        max_offset_cents = max_offset * tick_size * 100
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")
        await message.answer(
            f"❌ Invalid format. Enter a number from 0 to {max_offset_cents:.1f} cents:",
            reply_markup=builder.as_markup(),
        )


@market_router.message(MarketOrderStates.waiting_reposition_threshold)
async def process_reposition_threshold(message: Message, state: FSMContext):
    """Handles reposition threshold input (in cents)."""
    try:
        threshold_cents = float(message.text.strip())

        # Validation: must be positive
        if threshold_cents <= 0:
            builder = InlineKeyboardBuilder()
            builder.button(text="✖️ Cancel", callback_data="cancel")
            await message.answer(
                "❌ Threshold must be a positive number.\n\nEnter the threshold in cents (e.g., 0.5):",
                reply_markup=builder.as_markup(),
            )
            return

        # Get offset from state to validate threshold
        data = await state.get_data()
        offset_ticks = data.get("offset_ticks")
        tick_size = data.get("tick_size", TICK_SIZE)

        if offset_ticks is not None:
            offset_cents = offset_ticks * tick_size * 100

            # Validation: threshold must be less than offset
            # If threshold >= offset, the order will never be repositioned because
            # the maximum change in target price equals the offset
            if threshold_cents >= offset_cents:
                builder = InlineKeyboardBuilder()
                builder.button(text="✖️ Cancel", callback_data="cancel")
                await message.answer(
                    f"❌ Threshold ({threshold_cents:.2f}¢) must be less than offset ({offset_cents:.2f}¢).\n\n"
                    f"If threshold is greater than or equal to offset, the order will never be repositioned.\n\n"
                    f"Enter a threshold less than {offset_cents:.2f}¢:",
                    reply_markup=builder.as_markup(),
                )
                return

        # Save threshold to state
        await state.update_data(reposition_threshold_cents=threshold_cents)

        # Get all data for confirmation
        data = await state.get_data()
        market = data["market"]
        token_name = data["token_name"]
        direction = data["direction"]
        current_price = data["current_price"]
        target_price = data["target_price"]
        offset_ticks = data["offset_ticks"]
        amount = data["amount"]
        tick_size = data.get("tick_size", TICK_SIZE)

        # Convert offset from ticks to cents
        offset_cents = offset_ticks * tick_size * 100

        # Convert prices to cents and remove trailing zeros
        current_price_cents = current_price * 100
        target_price_cents = target_price * 100

        # Format prices without trailing zeros
        current_price_str = f"{current_price_cents:.2f}".rstrip("0").rstrip(".")
        target_price_str = f"{target_price_cents:.2f}".rstrip("0").rstrip(".")
        offset_cents_str = f"{offset_cents:.2f}".rstrip("0").rstrip(".")

        # Новое API: market - это словарь с полем 'title'
        market_title = market.get("title", "Unknown Market")

        confirm_text = f"""📋 <b>Settings Confirmation</b>

📊 <b>Market:</b>
Name: {market_title}
Outcome: {token_name}

💰 <b>Farm settings:</b>
Side: {direction} {token_name}
Current price: {current_price_str}¢
Current target price: {target_price_str}¢
Offset: {offset_cents_str}¢
Reposition threshold: {threshold_cents:.2f}¢

Amount: {amount} USDT"""

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Place Order", callback_data="confirm_yes")
        builder.button(text="✖️ Cancel", callback_data="cancel")
        builder.adjust(2)

        await message.answer(confirm_text, reply_markup=builder.as_markup())
        await state.set_state(MarketOrderStates.waiting_confirm)

    except ValueError:
        builder = InlineKeyboardBuilder()
        builder.button(text="✖️ Cancel", callback_data="cancel")
        await message.answer(
            "❌ Invalid format. Enter a number (e.g., 0.5 for 0.5 cents):",
            reply_markup=builder.as_markup(),
        )


@market_router.callback_query(
    F.data.startswith("confirm_"), MarketOrderStates.waiting_confirm
)
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    """Handles order placement confirmation."""
    confirm = callback.data.split("_")[1]

    if confirm != "yes":
        await callback.message.edit_text("""❌ Order placement cancelled""")
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    api_client = data.get("api_client")
    order_builder = data.get("order_builder")
    market = data.get("market", {})

    if not api_client or not order_builder:
        await callback.message.edit_text(
            """❌ API client not found. Please start over."""
        )
        await state.clear()
        await callback.answer()
        return

    await callback.message.edit_text("""🔄 Placing order...""")

    # Преобразуем side в Side enum
    side_str = data["order_side"].upper()
    side = Side.BUY if side_str == "BUY" else Side.SELL

    # Используем общий метод размещения ордера
    success, order_hash, order_api_id, error_message = await place_single_order(
        api_client=api_client,
        order_builder=order_builder,
        token_id=data["token_id"],
        side=side,
        price=float(data["target_price"]),
        amount=float(data["amount"]),
        market=market,
    )

    if success:
        # Save order to database
        try:
            telegram_id = callback.from_user.id
            market_id = data["market_id"]
            market = data.get("market", {})
            # Новое API: market - это словарь с полем 'title'
            market_title = market.get("title") if market else None
            # Получаем slug из state (был сохранен при обработке URL)
            market_slug = data.get("slug")
            token_id = data["token_id"]
            token_name = data["token_name"]
            side = data["direction"]  # BUY or SELL
            current_price = data["current_price"]
            target_price = data["target_price"]
            offset_ticks = data["offset_ticks"]
            tick_size = data.get("tick_size", TICK_SIZE)
            offset_cents = offset_ticks * tick_size * 100
            amount = data["amount"]
            reposition_threshold_cents = data.get("reposition_threshold_cents", 0.5)

            # Сохраняем ордер в базу данных
            # order_hash - это hash ордера (order.hash) для получения ордера через get_order_by_id
            # order_api_id сохраняется отдельно для off-chain отмены через cancel_orders
            await save_order(
                telegram_id=telegram_id,
                order_hash=order_hash,  # Hash ордера (order.hash)
                order_api_id=order_api_id,  # ID ордера из API (bigint string) для off-chain отмены
                market_id=market_id,
                market_title=market_title,
                market_slug=market_slug,
                token_id=token_id,
                token_name=token_name,
                side=side,
                current_price=current_price,
                target_price=target_price,
                offset_ticks=offset_ticks,
                offset_cents=offset_cents,
                amount=amount,
                status="OPEN",
                reposition_threshold_cents=reposition_threshold_cents,
            )
            logger.info(
                f"Order {order_hash} (API ID: {order_api_id}) successfully saved to DB for user {telegram_id}"
            )
        except Exception as e:
            logger.error(f"Error saving order to DB: {e}")

        # Get market slug for link
        market_slug = data.get("slug")
        market_url = f"https://predict.fun/market/{market_slug}"

        # Отправляем финальное сообщение с удалением reply-клавиатуры
        await callback.message.answer(
            f"""✅ <b>Order successfully placed!</b>

📋 <b>Final Information:</b>
• Market: <a href="{market_url}">{market_title}</a>
• Side: {data["direction"]} {data["token_name"]}
• Price: {data["target_price"]:.6f}
• Amount: {data["amount"]} USDT
• Offset: {offset_cents:.2f}¢
• Reposition threshold: {reposition_threshold_cents:.2f}¢
• Order Hash: <code>{order_hash}</code>

💡 <b>Useful commands:</b>
• /orders - View and manage your orders
• /make_market - Place a new order
• /check_account - Check your balance and account statistics""",
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        error_text = f"""❌ <b>Failed to place order</b>

{error_message if error_message else "Please check your balance and order parameters."}

Please try again using the /make_market command."""
        await callback.message.answer(error_text, reply_markup=ReplyKeyboardRemove())

    await state.clear()
    await callback.answer()


@market_router.callback_query(F.data == "cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    """
    Universal handler for 'Cancel' button for all order placement states.
    Works in all MarketOrderStates.
    """
    # Send new message to remove keyboard
    await callback.message.answer(
        "❌ Order placement cancelled",
        reply_markup=ReplyKeyboardRemove(),
    )

    await state.clear()
    await callback.answer()

    # Send instruction message
    await callback.message.answer(
        """🔗 Platform: <a href="https://predict.fun?ref=73581">predict.fun</a>

Use the /make_market command to place an order.
Use the /orders command to manage your orders.
Use the /check_account command to check your balance and account statistics.
Use the /set_proxy command to configure proxy server.
Use the /help command to view instructions.
Use the /support command to contact administrator."""
    )
