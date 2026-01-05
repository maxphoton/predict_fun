# Тесты для Predict.fun API

## Структура тестов

- `test_predict_api_client.py` - Тесты для методов `bot/predict_api/client.py` (testnet API)
  - `TestPublicMethods` - Публичные методы API (не требуют аутентификации)
  - `TestPrivateMethods` - Приватные методы API (требуют JWT токен)
  - `TestOrderMethods` - Методы работы с ордерами
  - `TestErrorHandling` - Обработка ошибок
  - `TestClientInitialization` - Инициализация клиента
  - `TestAPIBaseURL` - Проверка использования правильного API URL
  - `TestIntegration` - Интеграционные тесты
- `test_sdk_operations.py` - Тесты для SDK операций `bot/predict_api/sdk_operations.py` (mainnet)
- `test_sync_orders.py` - Тесты для синхронизации ордеров

## Запуск тестов

```bash
# Запустить все тесты
pytest tests/

# Запустить только тесты API клиента (testnet)
pytest tests/test_predict_api_client.py -v

# Запустить только тесты SDK операций (mainnet)
pytest tests/test_sdk_operations.py -v

# Запустить с подробным выводом
pytest tests/test_predict_api_client.py -v -s

# Запустить конкретный тест
pytest tests/test_predict_api_client.py::TestPublicMethods::test_get_markets -v
```

## Настройка для тестирования

### Переменные окружения

Тесты автоматически устанавливают `TEST_MODE` в зависимости от файла:
- `test_predict_api_client.py` → `TEST_MODE=true` (testnet)
- `test_sdk_operations.py` → `TEST_MODE=false` (mainnet)

### Тесты API клиента (testnet)

Файл `test_predict_api_client.py` использует тестовый API: `https://api-testnet.predict.fun/v1`

#### Публичные методы (не требуют credentials)

Следующие методы можно тестировать без дополнительных данных:
- `get_markets()` - получение списка рынков
- `get_market()` - получение рынка по ID
- `get_orderbook()` - получение orderbook
- `get_market_stats()` - статистика рынка
- `get_market_last_sale()` - последняя продажа
- `get_categories()` - список категорий
- `get_category()` - категория по slug
- `get_order_matches()` - события совпадения ордеров

**На testnet не требуется API key для этих методов.**

#### Приватные методы (требуют Predict Account credentials)

Для тестирования следующих методов нужны тестовые credentials:

**Переменные окружения:**
```bash
export TEST_PREDICT_ACCOUNT_ADDRESS=0x...      # Deposit address (адрес смарт-кошелька)
export TEST_PRIVY_WALLET_PRIVATE_KEY=0x...     # Приватный ключ Privy Wallet
export TEST_API_KEY=""                         # На testnet может быть пустым
export RPC_URL_TEST=https://data-seed-prebsc-1-s1.binance.org:8545/
```

**Где взять данные для Predict Account:**
- **TEST_PREDICT_ACCOUNT_ADDRESS** - это deposit address (адрес смарт-кошелька), можно найти на странице портфолио: https://predict.fun/portfolio/
- **TEST_PRIVY_WALLET_PRIVATE_KEY** - приватный ключ Privy Wallet, можно экспортировать из настроек аккаунта: https://predict.fun/account/settings

**Методы:**
- `get_my_orders()` - получение ордеров пользователя
- `get_positions()` - получение позиций
- `get_account()` - информация об аккаунте
- `cancel_orders()` - отмена ордеров из orderbook (off-chain)
- `place_order()` - размещение ордера (требует SDK для подписи ордера, затем размещение через REST API)

**Тесты для приватных методов:**
- `test_get_my_orders_with_auth` - получение ордеров с аутентификацией
- `test_get_positions` - получение позиций
- `test_get_account` - получение информации об аккаунте
- `test_place_order` - размещение ордера (требует OrderBuilder и реальные данные рынка)

**Важно:** 
- Если credentials не установлены, тесты для приватных методов будут автоматически пропущены (`pytest.skip`)
- Все тесты используют только **Predict Account** (смарт-кошельки), поддержка EOA удалена
- Для Predict Account используется метод аутентификации `signPredictAccountMessage`
- Рекомендуется пополнить Privy Wallet тестовыми BNB для оплаты газа при on-chain операциях (если тестируете `place_order`)
- **API не будет работать, если на аккаунте не было активности!** Необходимо совершить хотя бы одну сделку через веб-интерфейс

**Пример настройки в файле теста:**

Можно также изменить значения в начале файла `tests/test_predict_api_client.py`:

```python
TEST_PREDICT_ACCOUNT_ADDRESS = os.getenv('TEST_PREDICT_ACCOUNT_ADDRESS', '0x...')
TEST_PRIVY_WALLET_PRIVATE_KEY = os.getenv('TEST_PRIVY_WALLET_PRIVATE_KEY', '0x...')
TEST_API_KEY = os.getenv('TEST_API_KEY', '')
```

### Тесты SDK операций (mainnet)

Файл `test_sdk_operations.py` тестирует функции из `bot/predict_api/sdk_operations.py`:
- `get_usdt_balance()` - получение баланса USDT (on-chain)
- `build_and_sign_limit_order()` - построение и подпись ордеров
- `cancel_orders_via_sdk()` - отмена ордеров через SDK (on-chain)
- `set_approvals()` - установка approvals (on-chain транзакции)

**ВАЖНО: Эти тесты используют MAINNET и могут выполнять реальные транзакции!**

#### Настройка для mainnet

**Переменные окружения:**
```bash
export MAINNET_PREDICT_ACCOUNT_ADDRESS=0x...      # Deposit address (адрес смарт-кошелька)
export MAINNET_PRIVY_WALLET_PRIVATE_KEY=0x...      # Приватный ключ Privy Wallet
export RPC_URL=https://bsc-dataseed.binance.org/   # RPC URL для mainnet
```

**Где взять данные:**
- **MAINNET_PREDICT_ACCOUNT_ADDRESS** - deposit address (адрес смарт-кошелька) со страницы портфолио: https://predict.fun/portfolio/
- **MAINNET_PRIVY_WALLET_PRIVATE_KEY** - приватный ключ Privy Wallet из настроек аккаунта: https://predict.fun/account/settings

**Пример настройки в файле теста:**

Можно также изменить значения в начале файла `tests/test_sdk_operations.py`:

```python
MAINNET_PREDICT_ACCOUNT_ADDRESS = os.getenv('MAINNET_PREDICT_ACCOUNT_ADDRESS', '0x...')
MAINNET_PRIVY_WALLET_PRIVATE_KEY = os.getenv('MAINNET_PRIVY_WALLET_PRIVATE_KEY', '0x...')
MAINNET_RPC_URL = os.getenv('RPC_URL', 'https://bsc-dataseed.binance.org/')
```

#### Предупреждения

- ⚠️ Тесты используют **MAINNET** - реальную сеть с реальными средствами
- ⚠️ Тест `test_set_approvals` может выполнить реальные транзакции на mainnet (до 5 транзакций)
- ⚠️ Убедитесь, что у вас есть баланс BNB на Privy Wallet для оплаты газа
- ⚠️ Тесты автоматически пропускаются, если credentials не установлены
- ⚠️ `set_approvals` имеет таймаут 10 минут (600 секунд) - если транзакции не проходят, тест завершится с ошибкой таймаута

#### Особенности тестов SDK

1. **`test_set_approvals`**:
   - Может выполнить до 5 on-chain транзакций
   - Каждая транзакция ждет подтверждения до 120 секунд
   - Общий таймаут: 10 минут
   - Если на Privy Wallet нет BNB, тест покажет ошибку "insufficient funds for gas" (это нормально)

2. **`test_get_usdt_balance`**:
   - Читает баланс USDT из блокчейна
   - Не требует газа (только чтение)

3. **`test_build_and_sign_limit_order`**:
   - Создает и подписывает ордер (off-chain)
   - Не требует газа
   - Не размещает ордер в orderbook (только создает подпись)

4. **`test_cancel_orders_via_sdk`**:
   - Требует реальные ордера для отмены
   - Выполняет on-chain транзакцию (требует газа)

## Примечания

- На testnet не требуется API key для публичных методов
- **Все тесты используют только Predict Account** (смарт-кошельки)
  - Поддержка EOA (Externally Owned Accounts) удалена из кода
  - Параметр `is_predict_account` больше не существует в `PredictAPIClient`
- Тесты автоматически пропускаются (`pytest.skip`), если нет доступных credentials
- Для полного покрытия нужны:
  - Тестовые credentials на testnet (для `test_predict_api_client.py`)
  - Реальные credentials на mainnet (для `test_sdk_operations.py`)
- **API не будет работать, если на аккаунте не было активности!**
  - Необходимо совершить хотя бы одну сделку через веб-интерфейс перед использованием API
- Размещение ордеров через REST API **не требует газа** (off-chain операция)
- Отмена ордеров через SDK **требует газа** (on-chain транзакция)
- Установка approvals **требует газа** (on-chain транзакции)

## Изменения в тестах

### Удаленные тесты

- `test_client_init_predict_account` - удален, так как теперь все тесты используют только Predict Account
- Тест `test_client_init` проверяет базовую инициализацию клиента без параметра `is_predict_account`

### Обновленные фикстуры

- `test_client` - создает клиент без параметра `is_predict_account`
- `authenticated_client` - создает аутентифицированный клиент для Predict Account

## Устранение проблем

### Тест зависает на `test_set_approvals`

Если тест зависает:
1. Проверьте, что RPC URL доступен и отвечает
2. Убедитесь, что на Privy Wallet есть BNB для газа
3. Тест имеет таймаут 10 минут - если превышен, будет ошибка таймаута

### Ошибка "insufficient funds for gas"

Это нормально, если на Privy Wallet нет BNB. Тест покажет ошибку и завершится успешно (PASSED), так как проверяет корректную обработку ошибок.

### Тесты пропускаются

Если все тесты пропускаются:
1. Проверьте, что переменные окружения установлены правильно
2. Убедитесь, что адреса и ключи корректны
3. Для testnet: проверьте `TEST_PREDICT_ACCOUNT_ADDRESS` и `TEST_PRIVY_WALLET_PRIVATE_KEY`
4. Для mainnet: проверьте `MAINNET_PREDICT_ACCOUNT_ADDRESS` и `MAINNET_PRIVY_WALLET_PRIVATE_KEY`

### InvalidSignerError

Если получаете `InvalidSignerError`:
1. Убедитесь, что `TEST_PREDICT_ACCOUNT_ADDRESS` / `MAINNET_PREDICT_ACCOUNT_ADDRESS` - это deposit address (адрес смарт-кошелька), а не Privy Wallet address
   - Deposit address можно найти на странице портфолио: https://predict.fun/portfolio/
2. Убедитесь, что `TEST_PRIVY_WALLET_PRIVATE_KEY` / `MAINNET_PRIVY_WALLET_PRIVATE_KEY` - это приватный ключ Privy Wallet (владелец Predict Account)
   - Приватный ключ можно экспортировать из настроек: https://predict.fun/account/settings
3. Проверьте, что Predict Account зарегистрирован в сети (testnet или mainnet)
4. Убедитесь, что на аккаунте была активность (совершена хотя бы одна сделка через веб-интерфейс)
5. Проверьте, что используете правильную сеть (testnet для `test_predict_api_client.py`, mainnet для `test_sdk_operations.py`)

### Ошибка при создании клиента

Если получаете ошибку `TypeError: PredictAPIClient.__init__() got an unexpected keyword argument 'is_predict_account'`:
- Это означает, что в коде используется устаревший параметр `is_predict_account`
- Все тесты обновлены и больше не используют этот параметр
- `PredictAPIClient` теперь работает только с Predict Account (параметр удален)
