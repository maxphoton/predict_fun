"""
Операции через SDK для более эффективной работы с ордерами.

Согласно документации: https://dev.predict.fun/doc-679306

SDK предоставляет методы для:
- Получения баланса USDT (on-chain)
- Отмены ордеров через контракты (on-chain транзакции)
- Построения и подписи ордеров (затем размещение через REST API)
- Размещения ордеров (общий метод для использования в разных местах)
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Callable

from predict_sdk import OrderBuilder, Side, BuildOrderInput, LimitHelperInput, CancelOrdersOptions

# Константа для размера тика (совпадает с config.TICK_SIZE)
TICK_SIZE = 0.001

logger = logging.getLogger(__name__)


def calculate_new_target_price(
    new_current_price: float,
    side: str,
    offset_ticks: int,
    tick_size: float = TICK_SIZE
) -> float:
    """
    Вычисляет новую целевую цену с использованием сохраненного offset_ticks.
    
    Использует ту же логику, что и при создании ордера.
    
    Args:
        new_current_price: Новая текущая цена рынка
        side: BUY или SELL
        offset_ticks: Отступ в тиках (из БД)
        tick_size: Размер тика (по умолчанию 0.001)
    
    Returns:
        Новая целевая цена
    """
    # Вычисляем целевую цену так же, как при создании ордера
    if side == "BUY":
        target = new_current_price - offset_ticks * tick_size
    else:  # SELL
        target = new_current_price + offset_ticks * tick_size
    
    # Ограничиваем диапазоном 0.001 - 0.999 (требования API)
    MIN_PRICE = 0.001
    MAX_PRICE = 0.999
    target = max(MIN_PRICE, min(MAX_PRICE, target))
    target = round(target, 3)
    
    # Проверяем, что после округления цена все еще в допустимом диапазоне
    if target < MIN_PRICE:
        target = MIN_PRICE
    elif target > MAX_PRICE:
        target = MAX_PRICE
    
    return target


async def get_usdt_balance(order_builder: OrderBuilder) -> int:
    """
    Получить баланс USDT через SDK (on-chain).
    
    Согласно документации: https://dev.predict.fun/doc-679306#how-to-check-usdt-balance
    
    Args:
        order_builder: Экземпляр OrderBuilder
    
    Returns:
        Баланс USDT в wei (int)
    
    Example:
        balance_wei = await get_usdt_balance(order_builder)
        balance_usdt = balance_wei / 1e18
    """
    try:
        # SDK метод balanceOf() синхронный, оборачиваем в asyncio.to_thread
        # В Python SDK balanceOf требует аргумент "USDT" для указания токена
        balance_wei = await asyncio.to_thread(order_builder.balance_of, "USDT")
        logger.info(f"Баланс USDT получен: {balance_wei} wei ({balance_wei / 1e18:.6f} USDT)")
        return balance_wei
    except Exception as e:
        logger.error(f"Ошибка при получении баланса USDT: {e}")
        return 0


async def cancel_orders_via_sdk(
    order_builder: OrderBuilder,
    orders: List[Dict],
    is_neg_risk: bool = False,
    is_yield_bearing: bool = False
) -> Dict:
    """
    Отменить ордера через SDK (on-chain транзакции).
    
    Согласно документации: https://dev.predict.fun/doc-679306#how-to-cancel-orders
    
    Args:
        order_builder: Экземпляр OrderBuilder
        orders: Список ордеров для отмены. Каждый элемент может быть:
            - Словарем из API ответа: {'order': {...}, 'isNegRisk': bool, 'isYieldBearing': bool}
            - Словарем с данными ордера напрямую: {...}
            - Объектом Order из SDK
        is_neg_risk: True если это NegRisk рынок (используется если не указано в order_data)
        is_yield_bearing: True если это Yield Bearing рынок (используется если не указано в order_data)
    
    Returns:
        Словарь с результатом: {
            'success': bool,              # True если все группы отменены успешно
            'receipt': Optional[dict],    # Transaction receipt первой успешной группы
            'receipts': List[dict],       # Список всех transaction receipts
            'cause': Optional[str]        # Причина ошибки если неуспешно (объединенные причины всех групп)
        }
    
    Note:
        - Более эффективно чем отмена через REST API
        - Требует on-chain транзакцию (gas fees)
        - Автоматически группирует ордера по isNegRisk и isYieldBearing и отменяет каждую группу отдельно
        - SDK принимает список объектов Order или словарей, которые он преобразует
    """
    try:
        # Преобразуем словари в формат, который принимает SDK
        # SDK метод cancelOrders принимает список Order объектов
        # Но может работать и со словарями, которые он преобразует
        
        order_objects = []
        for order_data in orders:
            if isinstance(order_data, dict):
                # Если передан словарь с полем 'order', извлекаем его
                # Это формат из API ответа: {'order': {...}, 'isNegRisk': bool, ...}
                if 'order' in order_data:
                    order_dict = order_data['order']
                    # Извлекаем isNegRisk и isYieldBearing из родительского объекта
                    # если они не были указаны явно
                    current_is_neg_risk = order_data.get('isNegRisk', is_neg_risk)
                    current_is_yield_bearing = order_data.get('isYieldBearing', is_yield_bearing)
                else:
                    # Уже словарь с данными ордера
                    order_dict = order_data
                    current_is_neg_risk = is_neg_risk
                    current_is_yield_bearing = is_yield_bearing
                
                # SDK может принимать словари и преобразовывать их в Order
                # Но для группировки по isNegRisk/isYieldBearing нужно обрабатывать отдельно
                # Пока добавляем как есть, SDK должен обработать
                order_objects.append({
                    'order': order_dict,
                    'isNegRisk': current_is_neg_risk,
                    'isYieldBearing': current_is_yield_bearing
                })
            else:
                # Уже объект Order из SDK
                order_objects.append(order_data)
        
        if not order_objects:
            logger.warning("Нет ордеров для отмены")
            return {'success': False, 'cause': 'No orders to cancel'}
        
        # Группируем ордера по isNegRisk и isYieldBearing
        # Согласно документации, нужно вызывать cancelOrders отдельно для каждой группы
        groups = {}
        for item in order_objects:
            if isinstance(item, dict):
                if 'order' in item:
                    order_dict = item['order']
                    group_key = (item.get('isNegRisk', is_neg_risk), item.get('isYieldBearing', is_yield_bearing))
                else:
                    order_dict = item
                    group_key = (is_neg_risk, is_yield_bearing)
            else:
                # Объект Order из SDK - используем значения по умолчанию
                order_dict = item
                group_key = (is_neg_risk, is_yield_bearing)
            
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(order_dict)
        
        # Отменяем каждую группу отдельно
        all_success = True
        all_receipts = []
        all_causes = []
        
        for (group_is_neg_risk, group_is_yield_bearing), group_orders in groups.items():
            logger.info(f"Отменяем группу из {len(group_orders)} ордеров: isNegRisk={group_is_neg_risk}, isYieldBearing={group_is_yield_bearing}")
            
            options = CancelOrdersOptions(
                is_neg_risk=group_is_neg_risk,
                is_yield_bearing=group_is_yield_bearing
            )
            
            # SDK метод синхронный, оборачиваем в asyncio.to_thread
            result = await asyncio.to_thread(
                order_builder.cancel_orders,
                group_orders,
                options
            )
            
            if result.success:
                logger.info(f"Успешно отменено {len(group_orders)} ордеров в группе")
                if hasattr(result, 'receipt') and result.receipt:
                    all_receipts.append(result.receipt)
            else:
                logger.error(f"Ошибка отмены группы ордеров: {result.cause}")
                all_success = False
                if hasattr(result, 'cause') and result.cause:
                    all_causes.append(f"Group (isNegRisk={group_is_neg_risk}, isYieldBearing={group_is_yield_bearing}): {result.cause}")
        
        # Возвращаем объединенный результат
        return {
            'success': all_success,
            'receipt': all_receipts[0] if all_receipts else None,  # Возвращаем первый receipt
            'receipts': all_receipts,  # Все receipts для всех групп
            'cause': '; '.join(all_causes) if all_causes else None
        }
        
    except Exception as e:
        logger.error(f"Исключение при отмене ордеров через SDK: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {'success': False, 'cause': str(e)}


async def build_and_sign_limit_order(
    order_builder: OrderBuilder,
    side: Side,
    token_id: str,
    price_per_share_wei: int,
    quantity_wei: int,
    fee_rate_bps: int,
    is_neg_risk: bool = False,
    is_yield_bearing: bool = False,
    expires_at: Optional[datetime] = None
) -> Optional[Dict]:
    """
    Построить и подписать LIMIT ордер через SDK.
    
    Согласно документации: https://dev.predict.fun/doc-679306#how-to-create-a-limit-order-recommended
    
    Args:
        order_builder: Экземпляр OrderBuilder
        side: Направление ордера (Side.BUY или Side.SELL)
        token_id: ID токена (onChainId из outcomes)
        price_per_share_wei: Цена за акцию в wei
        quantity_wei: Количество акций в wei
        fee_rate_bps: Комиссия в базисных пунктах (из market.feeRateBps)
        is_neg_risk: True если это NegRisk рынок
        is_yield_bearing: True если это Yield Bearing рынок
        expires_at: Дата истечения ордера (datetime). Если None, SDK использует значение по умолчанию (30 дней)
    
    Returns:
        Словарь с подписанным ордером: {
            'order': dict,      # Объект ордера (для отправки в API)
            'signature': str,   # Подпись ордера
            'hash': str         # Hash ордера
        }
        Или None в случае ошибки
    """
    try:
        # Шаг 1: Рассчитываем суммы для ордера
        amounts = await asyncio.to_thread(
            order_builder.get_limit_order_amounts,
            LimitHelperInput(
                side=side,
                price_per_share_wei=price_per_share_wei,
                quantity_wei=quantity_wei
            )
        )
        
        # Отладочный лог: проверяем структуру объекта amounts
        logger.debug(f"OrderAmounts object type: {type(amounts)}")
        logger.debug(f"OrderAmounts attributes: {[attr for attr in dir(amounts) if not attr.startswith('_')]}")
        if hasattr(amounts, '__dict__'):
            logger.debug(f"OrderAmounts __dict__: {amounts.__dict__}")
        
        # Шаг 2: Строим ордер
        # Определяем expires_at: используем переданное значение или значение по умолчанию (30 дней)
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        
        order = await asyncio.to_thread(
            order_builder.build_order,
            "LIMIT",
            BuildOrderInput(
                side=side,
                token_id=token_id,
                maker_amount=str(amounts.maker_amount),
                taker_amount=str(amounts.taker_amount),
                fee_rate_bps=fee_rate_bps,
                expires_at=expires_at
            )
        )
        
        # Шаг 3: Генерируем typed data
        typed_data = await asyncio.to_thread(
            order_builder.build_typed_data,
            order,
            is_neg_risk=is_neg_risk,
            is_yield_bearing=is_yield_bearing
        )
        
        # Шаг 4: Подписываем ордер
        signed_order = await asyncio.to_thread(
            order_builder.sign_typed_data_order,
            typed_data
        )
        
        # Шаг 5: Вычисляем hash ордера
        order_hash = await asyncio.to_thread(
            order_builder.build_typed_data_hash,
            typed_data
        )
        
        # Извлекаем signature из signed_order
        signature = signed_order.signature if hasattr(signed_order, 'signature') else None
        if not signature:
            logger.error("Signature отсутствует в signed_order")
            return None
        
        # Явно собираем объект order для API из данных SDK
        # Python SDK использует snake_case, но API требует camelCase
        order_dict = {
            'hash': order_hash,
            'salt': str(order.salt),
            'maker': str(order.maker),
            'signer': str(order.signer),
            'taker': '0x0000000000000000000000000000000000000000',
            'tokenId': str(order.token_id),
            'makerAmount': str(order.maker_amount),
            'takerAmount': str(order.taker_amount),
            'expiration': int(order.expiration),
            'nonce': str(order.nonce),
            'feeRateBps': str(order.fee_rate_bps),
            'side': int(order.side),
            'signatureType': 0,
            'signature': signature
        }
        
        result = {
            'order': order_dict,
            'signature': signature,
            'hash': order_hash,
            'pricePerShare': str(amounts.price_per_share)
        }
        
        logger.info(f"Ордер успешно построен и подписан: hash={order_hash}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при построении и подписи ордера: {e}")
        return None


async def set_approvals(
    order_builder: OrderBuilder,
    is_yield_bearing: bool = False
) -> Dict:
    """
    Установить необходимые approvals для торговли.
    
    Согласно документации: https://dev.predict.fun/doc-679306#how-to-set-approvals
    
    Args:
        order_builder: Экземпляр OrderBuilder
        is_yield_bearing: True если работаем с Yield Bearing рынками
    
    Returns:
        Словарь с результатом: {
            'success': bool,
            'transactions': List[Dict]  # Список транзакций с результатами
        }
    """
    try:
        # SDK метод set_approvals синхронный, но может зависать при ожидании транзакций
        # Каждая транзакция может ждать до 120 секунд (wait_for_transaction_receipt)
        # Всего может быть до 5 транзакций, поэтому общий таймаут должен быть больше
        logger.info("Начинаем установку approvals (может занять несколько минут, до 10 минут)...")
        result = await asyncio.wait_for(
            asyncio.to_thread(
                order_builder.set_approvals,
                is_yield_bearing=is_yield_bearing
            ),
            timeout=600.0  # 10 минут таймаут (5 транзакций * 120 сек каждая)
        )
        logger.info("Установка approvals завершена")
        
        if result.success:
            logger.info("Approvals успешно установлены")
        else:
            # Собираем причины ошибок из неуспешных транзакций
            failed_causes = []
            for tx in result.transactions:
                if not tx.success and hasattr(tx, 'cause') and tx.cause:
                    # cause может быть Exception или словарем с code/message
                    if isinstance(tx.cause, dict):
                        cause_msg = tx.cause.get('message', str(tx.cause))
                    elif hasattr(tx.cause, 'message'):
                        cause_msg = tx.cause.message
                    else:
                        cause_msg = str(tx.cause)
                    failed_causes.append(cause_msg)
            cause_msg = '; '.join(failed_causes) if failed_causes else 'Unknown error'
            logger.warning(f"Некоторые approvals не установлены: {cause_msg}")
        
        # Преобразуем результат в словарь
        transactions = []
        for tx in result.transactions:
            # Правильно извлекаем cause (может быть Exception или словарем)
            cause_value = None
            if hasattr(tx, 'cause') and tx.cause:
                if isinstance(tx.cause, dict):
                    cause_value = tx.cause.get('message', str(tx.cause))
                elif hasattr(tx.cause, 'message'):
                    cause_value = tx.cause.message
                else:
                    cause_value = str(tx.cause)
            
            transactions.append({
                'success': tx.success,
                'cause': cause_value,
                'receipt': tx.receipt if hasattr(tx, 'receipt') else None
            })
        
        return {
            'success': result.success,
            'transactions': transactions
        }
        
    except asyncio.TimeoutError:
        logger.error("Таймаут при установке approvals (превышен лимит 10 минут). "
                     "Возможные причины: RPC не отвечает, транзакции не проходят, недостаточно газа")
        return {
            'success': False,
            'transactions': [],
            'cause': 'Timeout: approvals operation exceeded 10 minutes. Check RPC connection and gas balance'
        }
    except Exception as e:
        logger.error(f"Ошибка при установке approvals: {e}")
        return {
            'success': False,
            'transactions': [],
            'cause': str(e)
        }


async def place_single_order(
    api_client,
    order_builder: OrderBuilder,
    token_id: str,
    side: Side,
    price: float,
    amount: float,
    market: Optional[Dict] = None,
    market_id: Optional[int] = None
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Размещает один ордер на рынке (SDK + REST API).
    
    Общий метод для размещения ордеров, используется в market_router.py и sync_orders.py.
    
    Args:
        api_client: Экземпляр PredictAPIClient
        order_builder: Экземпляр OrderBuilder для SDK операций
        token_id: ID токена (onChainId из outcomes)
        side: Направление ордера (Side.BUY или Side.SELL)
        price: Цена за акцию (0.001 - 0.999) - должна быть уже пересчитана, если нужно
        amount: Сумма ордера в USDT
        market: Словарь с данными рынка (опционально, для получения feeRateBps, isNegRisk, isYieldBearing)
        market_id: ID рынка (опционально, используется если market не передан и нужно получить данные рынка)
    
    Returns:
        Tuple[bool, Optional[str], Optional[str], Optional[str]]: 
        (success, order_hash, order_api_id, error_message)
        - success: True если ордер успешно размещен
        - order_hash: Hash ордера (используется как order_id в БД)
        - order_api_id: ID ордера из API (bigint string, используется для off-chain отмены)
        - error_message: Сообщение об ошибке или None
    """
    try:
        # Валидация цены
        price_rounded = round(price, 3)  # API requires max 3 decimal places
        MIN_PRICE = 0.001
        MAX_PRICE = 0.999
        
        if price_rounded < MIN_PRICE:
            error_msg = f"Price {price_rounded} is less than minimum {MIN_PRICE}"
            logger.error(error_msg)
            return False, None, None, error_msg
        
        if price_rounded > MAX_PRICE:
            error_msg = f"Price {price_rounded} is greater than maximum {MAX_PRICE}"
            logger.error(error_msg)
            return False, None, None, error_msg
        
        # Получаем данные рынка для fee_rate_bps, is_neg_risk, is_yield_bearing
        if not market and market_id:
            try:
                market = await api_client.get_market(market_id=market_id)
            except Exception as e:
                logger.warning(f"Не удалось получить данные рынка {market_id}: {e}")
        
        if not market:
            # Используем значения по умолчанию
            fee_rate_bps = 100  # 1%
            is_neg_risk = False
            is_yield_bearing = False
        else:
            fee_rate_bps = market.get('feeRateBps', 100)
            is_neg_risk = market.get('isNegRisk', False)
            is_yield_bearing = market.get('isYieldBearing', False)
        
        # Преобразуем цену в wei
        price_per_share_wei = int(price_rounded * 1e18)
        
        # Преобразуем amount (USDT) в quantity_wei (количество акций)
        quantity = amount / price_rounded
        quantity_rounded = round(quantity)  # Округляем до целого числа акций
        quantity_wei = int(quantity_rounded * 1e18)
        
        # Шаг 1: Построить и подписать ордер через SDK
        signed_order_data = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=side,
            token_id=token_id,
            price_per_share_wei=price_per_share_wei,
            quantity_wei=quantity_wei,
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=is_neg_risk,
            is_yield_bearing=is_yield_bearing
        )
        
        if not signed_order_data:
            error_msg = "Failed to build and sign order"
            logger.error(error_msg)
            return False, None, None, error_msg
        
        # Шаг 2: Разместить ордер через REST API
        logger.info(f"Placing order with pricePerShare={signed_order_data.get('pricePerShare')}")
        logger.debug(f"Order data: {signed_order_data.get('order', {})}")
        
        result = await api_client.place_order(
            order=signed_order_data['order'],
            price_per_share=signed_order_data['pricePerShare'],
            strategy="LIMIT"
        )
        
        logger.info(f"Place order result: {result}")
        
        if result and result.get('code') == 'OK':
            # Возвращаем orderHash и orderId
            order_hash = signed_order_data.get('hash') or result.get('orderHash')
            order_api_id = result.get('orderId')  # ID ордера для off-chain отмены
            if order_hash:
                return True, order_hash, order_api_id, None
            else:
                error_msg = "orderHash not found in response. Cannot save order to database."
                logger.error(f"Error placing order: {error_msg}. Result: {result}")
                return False, None, None, error_msg
        else:
            # Извлекаем описание ошибки из ответа API
            error_description = result.get('error', {}).get('description') if result else None
            error_msg = error_description or result.get('message', 'Unknown error') if result else 'No response from API'
            logger.error(f"Error placing order: {error_msg}. Full result: {result}")
            return False, None, None, error_msg
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error placing order: {error_msg}", exc_info=True)
        return False, None, None, error_msg

