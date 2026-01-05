# Список внешних методов API, используемых в боте

Этот документ содержит полный список всех внешних методов API, которые используются в основном коде бота (исключая реализацию API клиента в `bot/predict_api/`).

## Статус миграции

**Текущее состояние:** Бот использует **старое API** (`opinion_clob_sdk.Client`).  
**Целевое состояние:** Миграция на **новое API** (`predict_api.PredictAPIClient` + `predict_sdk.OrderBuilder`).

---

## Методы старого API (opinion_clob_sdk.Client)

Все методы вызываются через экземпляр `Client`, создаваемый функцией `create_client()` из `bot/client_factory.py`.

### 1. `get_market(market_id, use_cache=True)`

**Описание:** Получение информации о рынке.

**Используется в:**
- `bot/market_router.py:78` - получение информации о рынке при размещении ордера через команду `/make_market`

**Параметры:**
- `market_id` (int): ID рынка
- `use_cache` (bool): Использовать кэш (по умолчанию True)

**Возвращает:** 
- Объект ответа с полями: `errno`, `errmsg`, `result.data` (данные рынка)

**Контекст использования:**
```python
# bot/market_router.py:72-87
async def get_market_info(client: Client, market_id: int, is_categorical: bool = False):
    if is_categorical:
        response = client.get_categorical_market(market_id=market_id)
    else:
        response = client.get_market(market_id=market_id, use_cache=True)
    
    if response.errno == 0:
        return response.result.data
```

---

### 2. `get_categorical_market(market_id)`

**Описание:** Получение информации о категориальном рынке (рынок с несколькими исходами).

**Используется в:**
- `bot/market_router.py:76` - получение информации о категориальном рынке при размещении ордера

**Параметры:**
- `market_id` (int): ID категориального рынка

**Возвращает:**
- Объект ответа с полями: `errno`, `errmsg`, `result.data` (данные категориального рынка, включая `child_markets`)

**Контекст использования:**
```python
# bot/market_router.py:72-87
async def get_market_info(client: Client, market_id: int, is_categorical: bool = False):
    if is_categorical:
        response = client.get_categorical_market(market_id=market_id)
    else:
        response = client.get_market(market_id=market_id, use_cache=True)
```

---

### 3. `get_orderbook(token_id)`

**Описание:** Получение orderbook (стакан заявок) для токена.

**Используется в:**
- `bot/market_router.py:103, 110` - получение orderbook для YES и NO токенов при размещении ордера
- `bot/sync_orders.py:153` - получение текущей цены рынка для синхронизации ордеров

**Параметры:**
- `token_id` (str): ID токена (yes_token_id или no_token_id)

**Возвращает:**
- Объект ответа с полями: `errno`, `errmsg`, `result` (объект orderbook с полями `bids` и `asks`)

**Контекст использования:**

**В market_router.py:**
```python
# bot/market_router.py:97-116
async def get_orderbooks(client: Client, yes_token_id: str, no_token_id: str):
    yes_orderbook = None
    no_orderbook = None
    
    try:
        response = client.get_orderbook(token_id=yes_token_id)
        if response.errno == 0:
            yes_orderbook = response.result if hasattr(response.result, 'bids') else getattr(response.result, 'data', response.result)
    except Exception as e:
        logger.error(f"Error getting orderbook for YES: {e}")
    
    try:
        response = client.get_orderbook(token_id=no_token_id)
        if response.errno == 0:
            no_orderbook = response.result if hasattr(response.result, 'bids') else getattr(response.result, 'data', response.result)
    except Exception as e:
        logger.error(f"Error getting orderbook for NO: {e}")
    
    return yes_orderbook, no_orderbook
```

**В sync_orders.py:**
```python
# bot/sync_orders.py:140-198
def get_current_market_price(client, token_id: str, side: str) -> Optional[float]:
    try:
        response = client.get_orderbook(token_id=token_id)
        
        if response.errno != 0:
            logger.error(f"Ошибка получения orderbook для токена {token_id}: errno={response.errno}")
            return None
        
        orderbook = response.result if not hasattr(response.result, 'data') else response.result.data
        
        bids = orderbook.bids if hasattr(orderbook, 'bids') else []
        asks = orderbook.asks if hasattr(orderbook, 'asks') else []
        
        if side == "BUY":
            # Для BUY берем best_bid (самый высокий бид)
            if bids and len(bids) > 0:
                bid_prices = [float(bid.price) for bid in bids if hasattr(bid, 'price')]
                if bid_prices:
                    return max(bid_prices)  # Самый высокий бид
        else:  # SELL
            # Для SELL берем best_ask (самый низкий аск)
            if asks and len(asks) > 0:
                ask_prices = [float(ask.price) for ask in asks if hasattr(ask, 'price')]
                if ask_prices:
                    return min(ask_prices)  # Самый низкий аск
```

---

### 4. `get_my_balances()`

**Описание:** Получение балансов пользователя (USDT и других токенов).

**Используется в:**
- `bot/market_router.py:208` - проверка баланса USDT перед размещением ордера

**Параметры:** Нет

**Возвращает:**
- Объект ответа с полями: `errno`, `errmsg`, `result` (объект с балансами, включая `balances` или `available_balance`)

**Контекст использования:**
```python
# bot/market_router.py:205-227
async def check_usdt_balance(client: Client, required_amount: float) -> Tuple[bool, dict]:
    """Checks if USDT balance is sufficient."""
    try:
        response = client.get_my_balances()
        
        if response.errno != 0:
            return False, {}
        
        balance_data = response.result if not hasattr(response.result, 'data') else response.result.data
        
        available = 0.0
        if hasattr(balance_data, 'balances') and balance_data.balances:
            for balance in balance_data.balances:
                available += float(getattr(balance, 'available_balance', 0))
        elif hasattr(balance_data, 'available_balance'):
            available = float(balance_data.available_balance)
        elif hasattr(balance_data, 'available'):
            available = float(balance_data.available)
        
        return available >= required_amount, balance_data
```

---

### 5. `enable_trading()`

**Описание:** Включение режима торговли. Необходимо вызывать перед размещением ордеров для активации торговых функций клиента.

**Используется в:**
- `bot/market_router.py:238` - перед размещением ордера при команде `/make_market`
- `bot/sync_orders.py:514` - перед размещением ордеров в батче при синхронизации

**Параметры:** Нет

**Возвращает:** None (метод изменяет состояние клиента)

**Контекст использования:**

**В market_router.py:**
```python
# bot/market_router.py:230-290
async def place_order(client: Client, order_params: dict) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        client.enable_trading()
        
        price = float(order_params['price'])
        price_rounded = round(price, 3)  # API requires max 3 decimal places
        
        # ... создание order_data ...
        
        def _place_order_sync():
            return client.place_order(order_data, check_approval=True)
        
        result = await asyncio.to_thread(_place_order_sync)
```

**В sync_orders.py:**
```python
# bot/sync_orders.py:502-578
def place_orders_batch(client, orders_params: List[Dict]) -> List:
    try:
        client.enable_trading()
        
        # Преобразуем параметры в PlaceOrderDataInput
        orders = []
        for params in orders_params:
            # ... создание order_input ...
            orders.append(order_input)
        
        # Размещаем ордера батчем
        results = client.place_orders_batch(orders, check_approval=False)
```

---

### 6. `place_order(order_data, check_approval=True)`

**Описание:** Размещение одного лимитного ордера.

**Используется в:**
- `bot/market_router.py:268` - размещение ордера при команде `/make_market`

**Параметры:**
- `order_data` (PlaceOrderDataInput): Данные ордера (marketId, tokenId, side, orderType, price, makerAmountInQuoteToken)
- `check_approval` (bool): Проверять approvals перед размещением (по умолчанию True)

**Возвращает:**
- Объект результата с полями: `errno` (0 = успех), `errmsg`, `result.order_data.order_id`

**Контекст использования:**
```python
# bot/market_router.py:230-290
async def place_order(client: Client, order_params: dict) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        client.enable_trading()
        
        price = float(order_params['price'])
        price_rounded = round(price, 3)
        
        order_data = PlaceOrderDataInput(
            marketId=order_params['market_id'],
            tokenId=order_params['token_id'],
            side=order_params['side'],
            orderType=LIMIT_ORDER,
            price=str(price_rounded),
            makerAmountInQuoteToken=order_params['amount']
        )
        
        def _place_order_sync():
            return client.place_order(order_data, check_approval=True)
        
        result = await asyncio.to_thread(_place_order_sync)
        
        if result.errno == 0:
            order_id = 'N/A'
            if hasattr(result, 'result'):
                if hasattr(result.result, 'order_data'):
                    order_data_obj = result.result.order_data
                    if hasattr(order_data_obj, 'order_id'):
                        order_id = order_data_obj.order_id
                    elif hasattr(order_data_obj, 'id'):
                        order_id = order_data_obj.id
            
            return True, str(order_id), None
        else:
            error_msg = result.errmsg if hasattr(result, 'errmsg') and result.errmsg else f"Error code: {result.errno}"
            return False, None, error_msg
```

---

### 7. `place_orders_batch(orders, check_approval=False)`

**Описание:** Размещение нескольких ордеров батчем (одной транзакцией).

**Используется в:**
- `bot/sync_orders.py:537` - размещение новых ордеров при синхронизации (перестановка ордеров)

**Параметры:**
- `orders` (List[PlaceOrderDataInput]): Список данных ордеров
- `check_approval` (bool): Проверять approvals перед размещением (по умолчанию False для батча)

**Возвращает:**
- Список результатов размещения для каждого ордера. Каждый результат имеет структуру:
  ```python
  {
      'success': bool,
      'result': API response объект с полями errno, errmsg, result.order_data.order_id,
      'error': Any (если есть ошибка)
  }
  ```

**Контекст использования:**
```python
# bot/sync_orders.py:502-578
def place_orders_batch(client, orders_params: List[Dict]) -> List:
    try:
        client.enable_trading()
        
        # Преобразуем параметры в PlaceOrderDataInput
        orders = []
        for params in orders_params:
            price_rounded = round(float(params["price"]), 3)
            
            amount_value = params["amount"]
            if isinstance(amount_value, str):
                amount_value = float(amount_value)
            
            order_input = PlaceOrderDataInput(
                marketId=params["market_id"],
                tokenId=params["token_id"],
                side=params["side"],
                orderType=LIMIT_ORDER,
                price=str(price_rounded),
                makerAmountInQuoteToken=amount_value
            )
            orders.append(order_input)
        
        # Размещаем ордера батчем
        results = client.place_orders_batch(orders, check_approval=False)
        
        # Обработка результатов...
        for i, result in enumerate(results):
            if result.get('success', False):
                result_data = result.get('result')
                if result_data and result_data.errno == 0:
                    order_id = result_data.result.order_data.order_id
                    logger.info(f"Размещен ордер: {order_id}")
```

---

### 8. `cancel_order(order_id)`

**Описание:** Отмена одного ордера.

**Используется в:**
- `bot/orders_dialog.py:228` - отмена ордера пользователем через диалог `/orders`

**Параметры:**
- `order_id` (str): ID ордера для отмены

**Возвращает:**
- Объект результата с полями: `errno` (0 = успех), `errmsg`

**Контекст использования:**
```python
# bot/orders_dialog.py:186-248
async def cancel_order_input_handler(message: Message, message_input: MessageInput, manager: DialogManager):
    """Обработчик ввода order_id для отмены ордера."""
    # ... проверки ...
    
    # Создаем клиент
    client = create_client(user)
    
    try:
        # Отменяем ордер
        result = client.cancel_order(order_id=order_id)
        
        if result.errno == 0:
            # Обновляем статус в БД
            await update_order_status(order_id, "canceled")
            await message.answer(f"✅ Order <code>{order_id}</code> successfully cancelled.")
        else:
            errmsg = getattr(result, 'errmsg', 'Unknown error')
            error_message = f"❌ Failed to cancel order <code>{order_id}</code>.\n\nError code: {result.errno}\nError message: {errmsg}"
            await message.answer(error_message)
```

---

### 9. `cancel_orders_batch(order_ids)`

**Описание:** Отмена нескольких ордеров батчем (одной транзакцией).

**Используется в:**
- `bot/sync_orders.py:467` - отмена старых ордеров при синхронизации (перед размещением новых)

**Параметры:**
- `order_ids` (List[str]): Список ID ордеров для отмены

**Возвращает:**
- Список результатов отмены для каждого ордера. Каждый результат имеет структуру:
  ```python
  {
      'success': bool,
      'result': API response объект с полями errno, errmsg,
      'error': Any (если есть ошибка)
  }
  ```

**Контекст использования:**
```python
# bot/sync_orders.py:455-499
def cancel_orders_batch(client, order_ids: List[str]) -> List[Dict]:
    """
    Отменяет ордера батчем.
    """
    try:
        results = client.cancel_orders_batch(order_ids)
        
        success_count = 0
        failed_count = 0
        
        for i, result in enumerate(results):
            if result.get('success', False):
                result_data = result.get('result')
                if result_data:
                    if hasattr(result_data, 'errno'):
                        if result_data.errno == 0:
                            logger.info(f"Отменен ордер: {order_ids[i]}")
                        else:
                            logger.error(f"Ошибка при отмене ордера {order_ids[i]}: errno={result_data.errno}")
                            failed_count += 1
                            success_count -= 1
```

---

### 10. `get_my_orders(market_id=0, status="", limit=10, page=1)`

**Описание:** Получение списка ордеров пользователя с пагинацией.

**Используется в:**
- `bot/opinion_api_wrapper.py:134` - обертка для получения ордеров (используется в `start_router.py:228`)

**Параметры:**
- `market_id` (int): ID рынка для фильтрации (0 = все рынки)
- `status` (str): Фильтр по статусу:
  - `"1"` = Pending (открытый/активный ордер)
  - `"2"` = Finished (исполненный ордер)
  - `"3"` = Canceled (отмененный ордер)
  - `""` = все статусы
- `limit` (int): Количество ордеров на странице (по умолчанию 10, максимум 20 без пагинации)
- `page` (int): Номер страницы для пагинации (по умолчанию 1)

**Возвращает:**
- Объект ответа с полями: `errno`, `errmsg`, `result.list` (список объектов ордеров)

**Контекст использования:**

**В opinion_api_wrapper.py:**
```python
# bot/opinion_api_wrapper.py:85-162
async def get_my_orders(
    client,
    market_id: int = 0,
    status: str = "",
    limit: int = 10,
    page: int = 1
) -> List[Any]:
    try:
        params = {
            'market_id': market_id,
            'status': status,
            'limit': limit,
            'page': page
        }
        
        # Вызываем API в отдельном потоке, так как SDK синхронный
        response = await asyncio.to_thread(client.get_my_orders, **params)
        
        if response.errno != 0:
            logger.warning(f"Ошибка при получении ордеров: errno={response.errno}")
            return []
        
        if not hasattr(response, 'result') or not response.result:
            return []
        
        if not hasattr(response.result, 'list'):
            return []
        
        order_list = response.result.list
        return order_list if order_list else []
```

**В start_router.py:**
```python
# bot/start_router.py:216-231
try:
    test_user_data = {
        'wallet_address': wallet_address,
        'private_key': private_key,
        'api_key': api_key_clean
    }
    
    test_client = create_client(test_user_data)
    
    # Пытаемся получить ордера пользователя для проверки подключения
    orders = await get_my_orders(test_client, market_id=0, status="", limit=1, page=1)
    
    # Если дошли сюда без исключений, значит подключение успешно
    logger.info(f"Успешная проверка подключения для пользователя {telegram_id}")
```

---

### 11. `get_order_by_id(order_id)`

**Описание:** Получение ордера по его ID.

**Используется в:**
- `bot/opinion_api_wrapper.py:183` - обертка для получения ордера по ID (используется в `sync_orders.py:303`)

**Параметры:**
- `order_id` (str): ID ордера

**Возвращает:**
- Объект ответа с полями: `errno`, `errmsg`, `result.order_data` (объект ордера со всеми полями)

**Контекст использования:**

**В opinion_api_wrapper.py:**
```python
# bot/opinion_api_wrapper.py:165-222
async def get_order_by_id(client, order_id: str) -> Optional[Any]:
    try:
        logger.info(f"Запрос ордера по ID из API: order_id={order_id}")
        
        # Вызываем API в отдельном потоке, так как SDK синхронный
        response = await asyncio.to_thread(client.get_order_by_id, order_id=order_id)
        
        if response.errno != 0:
            logger.warning(f"Ошибка при получении ордера: errno={response.errno}")
            return None
        
        if not hasattr(response, 'result') or not response.result:
            return None
        
        if not hasattr(response.result, 'order_data'):
            return None
        
        order = response.result.order_data
        return order
```

**В sync_orders.py:**
```python
# bot/sync_orders.py:300-343
# Проверяем статус ордера через API
try:
    api_order = await get_order_by_id(client, order_id)
    if api_order:
        # Получаем числовой статус из API и приводим к строке
        api_status = str(getattr(api_order, 'status', None))
        
        # Если статус в БД был 'pending', а в API стал 'Finished' (finished)
        if db_status == 'pending' and api_status == ORDER_STATUS_FINISHED:
            logger.info(f"Ордер {order_id} был pending, теперь finished. Обновляем БД и отправляем уведомление.")
            await update_order_status(order_id, 'finished')
            if bot:
                await send_order_filled_notification(bot, telegram_id, api_order)
            continue
        
        # Если статус в БД был 'pending', а в API стал 'Canceled' (canceled)
        elif db_status == 'pending' and api_status == ORDER_STATUS_CANCELED:
            logger.info(f"Ордер {order_id} был pending, теперь canceled. Обновляем БД.")
            await update_order_status(order_id, 'canceled')
            continue
```

---

## Сводная таблица использования методов

| Метод | Файл | Строка | Контекст использования |
|-------|------|--------|------------------------|
| `get_market()` | `market_router.py` | 78 | Получение информации о рынке при размещении ордера |
| `get_categorical_market()` | `market_router.py` | 76 | Получение информации о категориальном рынке |
| `get_orderbook()` | `market_router.py` | 103, 110 | Получение orderbook для YES/NO токенов при размещении ордера |
| `get_orderbook()` | `sync_orders.py` | 153 | Получение текущей цены рынка для синхронизации ордеров |
| `get_my_balances()` | `market_router.py` | 208 | Проверка баланса USDT перед размещением ордера |
| `enable_trading()` | `market_router.py` | 238 | Включение режима торговли перед размещением ордера |
| `enable_trading()` | `sync_orders.py` | 514 | Включение режима торговли перед батч размещением |
| `place_order()` | `market_router.py` | 268 | Размещение ордера при команде `/make_market` |
| `place_orders_batch()` | `sync_orders.py` | 537 | Размещение новых ордеров при синхронизации (перестановка) |
| `cancel_order()` | `orders_dialog.py` | 228 | Отмена ордера пользователем через диалог `/orders` |
| `cancel_orders_batch()` | `sync_orders.py` | 467 | Отмена старых ордеров при синхронизации (перед размещением новых) |
| `get_my_orders()` | `opinion_api_wrapper.py` | 134 | Обертка для получения ордеров (используется в `start_router.py:228`) |
| `get_order_by_id()` | `opinion_api_wrapper.py` | 183 | Обертка для получения ордера по ID (используется в `sync_orders.py:303`) |

---

## Файлы, использующие API методы

### Основные файлы

1. **`bot/market_router.py`** - Размещение ордеров через команду `/make_market`
   - Использует: `get_market()`, `get_categorical_market()`, `get_orderbook()`, `get_my_balances()`, `enable_trading()`, `place_order()`

2. **`bot/sync_orders.py`** - Автоматическая синхронизация и перестановка ордеров
   - Использует: `get_orderbook()`, `enable_trading()`, `place_orders_batch()`, `cancel_orders_batch()`
   - Использует через обертку: `get_order_by_id()` (из `opinion_api_wrapper.py`)

3. **`bot/orders_dialog.py`** - Диалог для просмотра и управления ордерами через команду `/orders`
   - Использует: `cancel_order()`

4. **`bot/start_router.py`** - Регистрация пользователей через команду `/start`
   - Использует через обертку: `get_my_orders()` (из `opinion_api_wrapper.py`) для проверки подключения к API

### Вспомогательные файлы

5. **`bot/opinion_api_wrapper.py`** - Обертки для асинхронного вызова синхронных методов SDK
   - Содержит обертки: `get_my_orders()`, `get_order_by_id()`
   - Используется в: `start_router.py`, `sync_orders.py`

---

## Примечания по миграции на новое API

### Доступные методы нового API

#### REST API методы (`PredictAPIClient`)

**Публичные методы (не требуют JWT):**
- `get_markets(first, after)` - список рынков
- `get_market(market_id)` - информация о рынке (включая категориальные)
- `get_orderbook(market_id)` - orderbook для рынка
- `get_market_stats(market_id)` - статистика рынка
- `get_market_last_sale(market_id)` - последняя продажа
- `get_categories(first, after, status, sort)` - список категорий
- `get_category(slug)` - категория по slug
- `get_order_matches(first, after, ...)` - события совпадения ордеров

**Приватные методы (требуют JWT):**
- `get_my_orders(first, after, status)` - ордера пользователя
- `get_order_by_id(order_hash)` - ордер по hash
- `get_positions(first, after)` - позиции пользователя
- `get_account()` - информация об аккаунте
- `set_referral(referral_code)` - установка реферального кода
- `place_order(order, price_per_share, strategy, slippage_bps, is_fill_or_kill)` - размещение ордера
- `cancel_orders(order_ids)` - удаление ордеров из orderbook (off-chain, не требует gas)

#### SDK операции (`bot/predict_api/sdk_operations.py`)

- `get_usdt_balance(order_builder)` - баланс USDT (on-chain чтение)
- `build_and_sign_limit_order(order_builder, side, token_id, price_per_share_wei, quantity_wei, fee_rate_bps, is_neg_risk, is_yield_bearing, expires_at)` - построение и подпись LIMIT ордера
- `cancel_orders_via_sdk(order_builder, orders, is_neg_risk, is_yield_bearing)` - отмена ордеров через SDK (on-chain, требует gas)
- `set_approvals(order_builder, is_yield_bearing)` - установка approvals (on-chain, требует gas)

### Маппинг методов старого API на новый

| Старый метод | Новый метод | Примечания |
|-------------|------------|------------|
| `get_market(market_id)` | `get_market(market_id)` | ✅ Прямая замена, но структура ответа изменилась |
| `get_categorical_market(market_id)` | `get_market(market_id)` | ✅ Используется тот же метод (категориальные рынки обрабатываются автоматически) |
| `get_orderbook(token_id)` | `get_orderbook(market_id)` | ⚠️ Изменился параметр: `token_id` → `market_id`, структура ответа изменилась |
| `get_my_balances()` | `get_usdt_balance(order_builder)` | ⚠️ Теперь через SDK (on-chain), требует `OrderBuilder` |
| `get_my_orders(market_id, status, limit, page)` | `get_my_orders(first, after, status)` | ⚠️ Изменилась пагинация: `limit/page` → `first/after`, убран параметр `market_id` |
| `get_order_by_id(order_id)` | `get_order_by_id(order_hash)` | ⚠️ Изменился параметр: `order_id` → `order_hash` |
| `place_order(order_data)` | `build_and_sign_limit_order()` + `place_order()` | ⚠️ Двухэтапный процесс: сначала SDK, потом REST API |
| `place_orders_batch(orders)` | Множественные вызовы `build_and_sign_limit_order()` + `place_order()` | ⚠️ Батч размещение через цикл |
| `cancel_order(order_id)` | `cancel_orders([order_id])` или `cancel_orders_via_sdk()` | ⚠️ Для off-chain: `cancel_orders()`, для on-chain: `cancel_orders_via_sdk()` |
| `cancel_orders_batch(order_ids)` | `cancel_orders(order_ids)` или `cancel_orders_via_sdk()` | ⚠️ Для off-chain: `cancel_orders()`, для on-chain: `cancel_orders_via_sdk()` |
| `enable_trading()` | `set_approvals(order_builder)` | ⚠️ Теперь on-chain транзакции (требует gas), вызывать **ОДИН РАЗ на кошелек** (не перед каждым ордером!) |

### Изменения в идентификаторах

- **Старое API:** `order_id` (строка, например `"def73c87-e120-11f0-8edd-0a58a9feac02"`)
- **Новое API:** 
  - `order.hash` (hash ордера, строка) - для получения ордера
  - `order.id` (строка, bigint) - для отмены через `cancel_orders()`

### Изменения в пагинации

- **Старое API:** `limit` и `page` (page-based пагинация)
- **Новое API:** `first` и `after` (cursor-based пагинация)
  - `first` - количество элементов (string, число)
  - `after` - cursor для следующей страницы (string, может быть None)
  - Возвращает `(items, cursor)` tuple

### Изменения в структуре orderbook

- **Старое API:** `get_orderbook(token_id)` - возвращает объект с `bids` и `asks` (объекты с полями `price`, `size`)
- **Новое API:** `get_orderbook(market_id)` - возвращает Dict:
  ```python
  {
      'marketId': int,
      'updateTimestampMs': int,
      'asks': [[price, size], ...],  # Массив массивов [цена, размер]
      'bids': [[price, size], ...]    # Массив массивов [цена, размер]
  }
  ```
  - ⚠️ Изменился параметр: `token_id` → `market_id`
  - ⚠️ Структура данных: объекты → массивы массивов
  - ⚠️ Orderbook хранит цены на основе исхода "Yes", для "No": `price_no = 1 - price_yes`

### Изменения в отмене ордеров

- **Старое API:** 
  - `cancel_order(order_id)` - отмена одного ордера (on-chain, требует gas)
  - `cancel_orders_batch(order_ids)` - отмена нескольких ордеров (on-chain, требует gas)

- **Новое API:** 
  - `cancel_orders(order_ids)` - удаление из orderbook (off-chain, **не требует gas**)
    - Принимает список `order_ids` (строки, bigint)
    - Возвращает `{'success': bool, 'removed': [...], 'noop': [...]}`
    - ⚠️ **НЕ отменяет ордер в блокчейне** - ордер может быть исполнен, если кто-то знает его hash
    - ⚠️ **Риск**: Используйте только если понимаете последствия
  - `cancel_orders_via_sdk(order_builder, orders, is_neg_risk, is_yield_bearing)` - полная on-chain отмена (требует gas)
    - Принимает список ордеров (словари или Order объекты)
    - Автоматически группирует по `isNegRisk` и `isYieldBearing`
    - ✅ **Отменяет ордер в блокчейне** - ордер инвалидирован и не может быть исполнен
    - ⚠️ **НЕ удаляет автоматически из orderbook** - ордер может остаться видимым, но это безопасно
    - ✅ **Рекомендуется** для большинства случаев (включая `sync_orders.py`)

**Важно: Что произойдет, если ордер отменен on-chain, но остался в orderbook?**
- Если кто-то попытается исполнить такой ордер, транзакция **провалится** на уровне смарт-контракта
- Ордер инвалидирован в блокчейне, исполнение невозможно
- Ордер может остаться видимым в orderbook, но это безопасно (не может быть исполнен)

### Изменения в размещении ордеров

- **Старое API:** `place_order(order_data)` - автоматически строит и подписывает ордер
- **Новое API:** Двухэтапный процесс:
  1. **SDK:** `build_and_sign_limit_order(order_builder, side, token_id, price_per_share_wei, quantity_wei, fee_rate_bps, is_neg_risk, is_yield_bearing, expires_at)`
     - Строит и подписывает ордер **локально** (приватный ключ не покидает ваше устройство)
     - Рассчитывает все необходимые поля: `nonce`, `salt`, `makerAmount`, `takerAmount`, `hash`
     - Подписывает ордер криптографической подписью (ECDSA)
     - Возвращает `{'order': {...}, 'pricePerShare': str, 'hash': str, 'signature': str}`
  2. **REST API:** `place_order(order, price_per_share, strategy, slippage_bps, is_fill_or_kill)`
     - Размещает **уже подписанный** ордер в orderbook
     - **Не требует газа** (off-chain операция)
     - Возвращает `{'code': 'OK', 'orderId': str, 'orderHash': str}`

**Почему нужна комбинация методов?**
- 🔒 **Безопасность**: Приватный ключ **никогда** не передается в API (остается локально)
- ✅ **Криптографическая подпись**: Подпись доказывает, что ордер создан владельцем приватного ключа
- 🔗 **Децентрализация**: Подпись проверяется на блокчейне при исполнении ордера
- 📝 **Правильные расчеты**: SDK правильно рассчитывает `nonce`, `salt`, `hash`, `makerAmount`, `takerAmount` и другие поля
- 🛡️ **Защита от подделки**: API не может создать ордер от вашего имени без вашей подписи

### Изменения в балансах

- **Старое API:** `get_my_balances()` - через REST API, возвращает все балансы
- **Новое API:** 
  - `get_usdt_balance(order_builder)` - через SDK (on-chain чтение)
    - Требует `OrderBuilder` из `predict_sdk`
    - Возвращает баланс USDT в wei (int)
    - Более актуальные данные (читает из блокчейна)
  - `get_positions(first, after)` - через REST API, возвращает позиции пользователя
    - Альтернатива для получения информации о позициях

### Изменения в enable_trading

- **Старое API:** `enable_trading()` - метод клиента, изменяет состояние (синхронный), вызывался перед каждым размещением ордера
- **Новое API:** `set_approvals(order_builder, is_yield_bearing)` - on-chain транзакции
  - Требует `OrderBuilder` из `predict_sdk`
  - Выполняет до 5 on-chain транзакций (требует gas)
  - Имеет таймаут 10 минут
  - **Нужно вызывать ОДИН РАЗ на кошелек** перед началом торговли (не перед каждым ордером!)
  - После установки approvals остаются активными и не требуют повторной установки
  - Если approvals уже установлены, повторный вызов безопасен (SDK проверит текущее состояние и пропустит уже установленные)
  - После установки approvals можно размещать ордера без повторного вызова `set_approvals`

### Удаленные методы

Следующие методы были удалены из нового API:
- ❌ `get_my_balances()` - заменен на `get_usdt_balance()` (SDK) или `get_positions()` (REST API)
- ❌ `get_categorical_market()` - теперь используется `get_market()` для всех типов рынков
- ❌ `cancel_order()` - заменен на `cancel_orders([order_id])` или `cancel_orders_via_sdk()`
- ❌ `cancel_orders_batch()` - заменен на `cancel_orders()` или `cancel_orders_via_sdk()`

### Важные отличия

1. **Аутентификация:**
   - Старое API: API key в заголовках
   - Новое API: JWT токен (Bearer Authentication) + API key
   - JWT токен автоматически обновляется при 401 ошибке

2. **Тип кошелька:**
   - Старое API: Поддержка EOA и Predict Account
   - Новое API: **Только Predict Account** (смарт-кошельки)
   - Требуется Deposit Address и Privy Wallet Private Key

3. **Gas fees:**
   - Размещение ордеров через REST API: **не требует газа** (off-chain)
   - Отмена через `cancel_orders()`: **не требует газа** (off-chain)
   - Отмена через `cancel_orders_via_sdk()`: **требует газа** (on-chain)
   - Установка approvals: **требует газа** (on-chain)

4. **Структура ответов:**
   - Старое API: `response.errno`, `response.errmsg`, `response.result`
   - Новое API: `{'success': bool, 'data': {...}, 'cursor': ...}` или `None` при ошибке

---

## Следующие шаги для миграции

1. ✅ Создан новый API клиент (`PredictAPIClient`) в `bot/predict_api/`
2. ✅ Созданы функции для SDK операций в `bot/predict_api/sdk_operations.py`
3. ✅ Реализованы все необходимые методы согласно OpenAPI спецификации
4. ✅ Удалены методы для обратной совместимости (EOA, proxy и т.д.)
5. ⏳ Обновить `market_router.py` для использования нового API
6. ⏳ Обновить `sync_orders.py` для использования нового API
7. ⏳ Обновить `orders_dialog.py` для использования нового API
8. ⏳ Обновить `start_router.py` для использования нового API
9. ⏳ Обновить или заменить `opinion_api_wrapper.py` на новый API

### Примеры миграции

#### Пример 1: Получение рынка

**Старый код:**
```python
response = client.get_market(market_id=market_id, use_cache=True)
if response.errno == 0:
    market_data = response.result.data
```

**Новый код:**
```python
from bot.predict_api import PredictAPIClient

api_client = PredictAPIClient(api_key, wallet_address, private_key)
market_data = await api_client.get_market(market_id=market_id)
# market_data уже словарь или None
```

#### Пример 2: Получение orderbook

**Старый код:**
```python
response = client.get_orderbook(token_id=token_id)
if response.errno == 0:
    orderbook = response.result
    bids = orderbook.bids  # Объекты с полями price, size
```

**Новый код:**
```python
orderbook = await api_client.get_orderbook(market_id=market_id)
if orderbook:
    bids = orderbook['bids']  # [[price, size], ...]
    asks = orderbook['asks']  # [[price, size], ...]
```

#### Пример 3: Размещение ордера

**Старый код:**
```python
client.enable_trading()  # Вызывалось перед каждым ордером
order_data = PlaceOrderDataInput(...)
result = client.place_order(order_data, check_approval=True)
```

**Новый код:**
```python
from bot.predict_api.sdk_operations import build_and_sign_limit_order, set_approvals
from predict_sdk import OrderBuilder, Side, ChainId, OrderBuilderOptions

# 1. Установить approvals (ОДИН РАЗ на кошелек, не перед каждым ордером!)
# Вызвать один раз при инициализации бота/кошелька
await set_approvals(order_builder, is_yield_bearing=False)

# 2. Построить и подписать ордер (можно вызывать многократно)
signed_order = await build_and_sign_limit_order(
    order_builder=order_builder,
    side=Side.BUY,
    token_id=token_id,
    price_per_share_wei=price_wei,
    quantity_wei=quantity_wei,
    fee_rate_bps=fee_rate_bps,
    is_neg_risk=is_neg_risk,
    is_yield_bearing=is_yield_bearing
)

# 3. Разместить ордер (можно вызывать многократно, approvals уже установлены)
result = await api_client.place_order(
    order=signed_order['order'],
    price_per_share=signed_order['pricePerShare'],
    strategy="LIMIT"
)
```

#### Пример 4: Отмена ордеров

**Старый код:**
```python
result = client.cancel_orders_batch(order_ids)
```

**Новый код (off-chain, не требует газа):**
```python
result = await api_client.cancel_orders(order_ids=order_ids)
# result = {'success': bool, 'removed': [...], 'noop': [...]}
```

**Новый код (on-chain, требует газа, рекомендуется для sync_orders.py):**
```python
from bot.predict_api.sdk_operations import cancel_orders_via_sdk

result = await cancel_orders_via_sdk(
    order_builder=order_builder,
    orders=orders,  # Список ордеров из API
    is_neg_risk=is_neg_risk,
    is_yield_bearing=is_yield_bearing
)
```

#### Пример 5: Получение баланса

**Старый код:**
```python
response = client.get_my_balances()
balance = response.result.available_balance
```

**Новый код:**
```python
from bot.predict_api.sdk_operations import get_usdt_balance

balance_wei = await get_usdt_balance(order_builder)
balance_usdt = balance_wei / 1e18
```

#### Пример 6: Получение ордеров

**Старый код:**
```python
response = client.get_my_orders(market_id=0, status="", limit=10, page=1)
orders = response.result.list
```

**Новый код:**
```python
orders, cursor = await api_client.get_my_orders(
    first=10,
    after=None,  # Для первой страницы
    status="OPEN"  # или None для всех
)
# Для следующей страницы: after=cursor
```

