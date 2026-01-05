"""
Тесты для bot/predict_api/client.py

Тестирует методы PredictAPIClient используя тестовый API:
https://api-testnet.predict.fun/v1

На testnet не требуется API key и x-api-key header для публичных методов.

Данные, необходимые для тестирования:
1. Публичные методы (get_market, get_orderbook, get_markets и т.д.):
   - Не требуют дополнительных данных
   - На testnet не требуется API key
   - Используют реальные данные с testnet API

2. Приватные методы (get_my_orders, get_positions, get_account, place_order, cancel_orders):
   - Требуют JWT токен (получается через аутентификацию)
   - Для получения JWT нужны:
     * api_key (на testnet может быть пустым для некоторых методов)
     * TEST_PREDICT_ACCOUNT_ADDRESS (deposit address Predict Account)
     * TEST_PRIVY_WALLET_PRIVATE_KEY (приватный ключ Privy Wallet)
   - Для place_order дополнительно нужен подписанный ордер (требует SDK)

3. Для полного тестирования place_order:
   - Нужен OrderBuilder из predict-sdk
   - Нужны реальные данные рынка (market_id, token_id, feeRateBps)
   - Нужен баланс USDT на тестовом Predict Account

ВАЖНО: Все тесты используют Predict Account (Smart Wallet), не EOA.
"""
import pytest
import os
from typing import Dict, List, Optional

from bot.predict_api.client import PredictAPIClient
from bot.predict_api.auth import get_api_base_url, get_rpc_url, get_chain_id
from bot.predict_api.sdk_operations import build_and_sign_limit_order
from predict_sdk import OrderBuilder, ChainId, Side, OrderBuilderOptions
from predict_sdk.errors import InvalidSignerError
from eth_account import Account
from eth_account.signers.local import LocalAccount

# Настраиваем переменные окружения для тестового API
os.environ['TEST_MODE'] = 'true'
os.environ['API_BASE_URL_TEST'] = 'https://api-testnet.predict.fun/v1'

# ============================================================================
# Переменные для тестирования приватных методов
# ============================================================================
# Для тестирования приватных методов (get_my_orders, get_positions, place_order и т.д.)
# установите эти переменные окружения или измените значения ниже:
#
# Для Predict Account:
# - TEST_PREDICT_ACCOUNT_ADDRESS - это deposit address (адрес смарт-кошелька)
#   Можно найти в настройках аккаунта на https://predict.fun/account/settings
# - TEST_PRIVY_WALLET_PRIVATE_KEY - приватный ключ Privy Wallet
#   Можно экспортировать из настроек аккаунта на https://predict.fun/account/settings

# Адрес Predict Account (deposit address) на BNB Testnet
TEST_PREDICT_ACCOUNT_ADDRESS = os.getenv('TEST_PREDICT_ACCOUNT_ADDRESS', '0x724dF00c9FfCE43A8C476C0b849a21e2d67311D6')

# Приватный ключ Privy Wallet для Predict Account
TEST_PRIVY_WALLET_PRIVATE_KEY = os.getenv('TEST_PRIVY_WALLET_PRIVATE_KEY', 'c9b2f16ea2bd6395c3e7c015bcedb658a8fd9d5c802583daabb1787dabad6095')

# API ключ (на testnet может быть пустым для некоторых методов)
TEST_API_KEY = os.getenv('TEST_API_KEY', '')

# RPC URL для testnet (автоматически используется при TEST_MODE=true)
TEST_RPC_URL = os.getenv('RPC_URL_TEST', 'https://data-seed-prebsc-1-s1.binance.org:8545/')

# Устанавливаем RPC_URL_TEST если не установлен
if 'RPC_URL_TEST' not in os.environ:
    os.environ['RPC_URL_TEST'] = TEST_RPC_URL

# Используем Predict Account credentials
ACTUAL_WALLET_ADDRESS = TEST_PREDICT_ACCOUNT_ADDRESS
ACTUAL_PRIVATE_KEY = TEST_PRIVY_WALLET_PRIVATE_KEY


@pytest.fixture
def test_client():
    """
    Создает тестовый клиент для testnet API.
    
    На testnet не требуется API key для публичных методов,
    но для приватных методов нужны тестовые credentials.
    
    Использует переменные, определенные в начале файла:
    - TEST_PREDICT_ACCOUNT_ADDRESS (Deposit Address)
    - TEST_PRIVY_WALLET_PRIVATE_KEY (Privy Wallet private key)
    """
    return PredictAPIClient(
        api_key=TEST_API_KEY,
        wallet_address=ACTUAL_WALLET_ADDRESS,
        private_key=ACTUAL_PRIVATE_KEY
    )


@pytest.fixture
def authenticated_client():
    """
    Создает аутентифицированный клиент для тестирования приватных методов.
    
    Использует Predict Account credentials (TEST_PREDICT_ACCOUNT_ADDRESS и TEST_PRIVY_WALLET_PRIVATE_KEY).
    
    Если credentials не установлены, возвращает None (тесты будут пропущены).
    """
    # Проверяем, что credentials установлены
    if not ACTUAL_WALLET_ADDRESS or not ACTUAL_PRIVATE_KEY:
        return None
    
    return PredictAPIClient(
        api_key=TEST_API_KEY,
        wallet_address=ACTUAL_WALLET_ADDRESS,
        private_key=ACTUAL_PRIVATE_KEY
    )


@pytest.fixture
def mock_market_data():
    """Мок данных рынка для тестов."""
    return {
        'id': 1,
        'title': 'Test Market',
        'question': 'Will this test pass?',
        'description': 'A test market',
        'status': 'UNPAUSED',
        'isNegRisk': False,
        'isYieldBearing': False,
        'feeRateBps': 100,
        'outcomes': [
            {'name': 'Yes', 'indexSet': 1, 'onChainId': '0x1', 'status': None},
            {'name': 'No', 'indexSet': 2, 'onChainId': '0x2', 'status': None}
        ],
        'conditionId': '0x123'
    }


@pytest.fixture
def mock_orderbook_data():
    """Мок данных orderbook для тестов."""
    return {
        'marketId': 1,
        'updateTimestampMs': 1234567890000,
        'asks': [[0.51, 100.0], [0.52, 200.0]],
        'bids': [[0.49, 150.0], [0.48, 250.0]]
    }


class TestPublicMethods:
    """Тесты для публичных методов (не требуют JWT)."""
    
    @pytest.mark.asyncio
    async def test_get_markets(self, test_client):
        """Тест получения списка рынков."""
        markets, cursor = await test_client.get_markets(first=10)
        
        # Проверяем, что получили список
        assert isinstance(markets, list)
        # Если есть рынки, проверяем структуру
        if markets:
            market = markets[0]
            assert 'id' in market
            assert 'title' in market
            assert 'question' in market
    
    @pytest.mark.asyncio
    async def test_get_markets_with_pagination(self, test_client):
        """Тест пагинации при получении рынков."""
        # Получаем первую страницу
        markets1, cursor1 = await test_client.get_markets(first=5)
        
        assert isinstance(markets1, list)
        
        # Если есть cursor, получаем следующую страницу
        if cursor1:
            markets2, cursor2 = await test_client.get_markets(first=5, after=cursor1)
            assert isinstance(markets2, list)
    
    @pytest.mark.asyncio
    async def test_get_market_by_id(self, test_client):
        """Тест получения рынка по ID."""
        # Сначала получаем список рынков, чтобы найти реальный ID
        markets, _ = await test_client.get_markets(first=1)
        
        if markets and len(markets) > 0:
            market_id = markets[0]['id']
            market = await test_client.get_market(market_id)
            
            assert market is not None
            assert market['id'] == market_id
            assert 'title' in market
            assert 'question' in market
            assert 'outcomes' in market
        else:
            pytest.skip("Нет доступных рынков на testnet для тестирования")
    
    @pytest.mark.asyncio
    async def test_get_orderbook(self, test_client):
        """Тест получения orderbook."""
        # Сначала получаем список рынков
        markets, _ = await test_client.get_markets(first=1)
        
        if markets and len(markets) > 0:
            market_id = markets[0]['id']
            orderbook = await test_client.get_orderbook(market_id)
            
            if orderbook:  # Orderbook может быть пустым
                assert 'marketId' in orderbook
                assert 'asks' in orderbook
                assert 'bids' in orderbook
                assert isinstance(orderbook['asks'], list)
                assert isinstance(orderbook['bids'], list)
        else:
            pytest.skip("Нет доступных рынков на testnet для тестирования")
    
    @pytest.mark.asyncio
    async def test_get_market_stats(self, test_client):
        """Тест получения статистики рынка."""
        # Сначала получаем список рынков
        markets, _ = await test_client.get_markets(first=1)
        
        if markets and len(markets) > 0:
            market_id = markets[0]['id']
            stats = await test_client.get_market_stats(market_id)
            
            if stats:  # Статистика может быть None
                assert isinstance(stats, dict)
        else:
            pytest.skip("Нет доступных рынков на testnet для тестирования")
    
    @pytest.mark.asyncio
    async def test_get_market_last_sale(self, test_client):
        """Тест получения последней продажи."""
        # Сначала получаем список рынков
        markets, _ = await test_client.get_markets(first=1)
        
        if markets and len(markets) > 0:
            market_id = markets[0]['id']
            last_sale = await test_client.get_market_last_sale(market_id)
            
            # last_sale может быть None если продаж еще не было
            if last_sale:
                assert isinstance(last_sale, dict)
                assert 'quoteType' in last_sale or 'priceInCurrency' in last_sale
        else:
            pytest.skip("Нет доступных рынков на testnet для тестирования")
    
    @pytest.mark.asyncio
    async def test_get_categories(self, test_client):
        """Тест получения списка категорий."""
        categories, cursor = await test_client.get_categories(first=10)
        
        assert isinstance(categories, list)
        # Если есть категории, проверяем структуру
        if categories:
            category = categories[0]
            assert 'id' in category or 'slug' in category
            assert 'title' in category or 'name' in category
    
    @pytest.mark.asyncio
    async def test_get_categories_with_filters(self, test_client):
        """Тест получения категорий с фильтрами."""
        # Тест с фильтром по статусу
        categories, _ = await test_client.get_categories(
            first=10,
            status='OPEN'
        )
        assert isinstance(categories, list)
        
        # Тест с сортировкой
        categories, _ = await test_client.get_categories(
            first=10,
            sort='PUBLISHED_AT_DESC'
        )
        assert isinstance(categories, list)
    
    @pytest.mark.asyncio
    async def test_get_category_by_slug(self, test_client):
        """Тест получения категории по slug."""
        # Сначала получаем список категорий
        categories, _ = await test_client.get_categories(first=1)
        
        if categories and len(categories) > 0:
            slug = categories[0].get('slug')
            if slug:
                category = await test_client.get_category(slug)
                
                if category:
                    assert isinstance(category, dict)
                    assert category.get('slug') == slug
        else:
            pytest.skip("Нет доступных категорий на testnet для тестирования")
    
    @pytest.mark.asyncio
    async def test_get_order_matches(self, test_client):
        """Тест получения событий совпадения ордеров."""
        matches, cursor = await test_client.get_order_matches(first=10)
        
        assert isinstance(matches, list)
        # Если есть matches, проверяем структуру
        if matches:
            match = matches[0]
            assert 'market' in match or 'transactionHash' in match


class TestPrivateMethods:
    """
    Тесты для приватных методов (требуют JWT).
    
    ВАЖНО: Для полного тестирования этих методов нужны:
    - Реальные тестовые credentials (wallet_address, private_key)
    - Или мокирование JWT токена
    
    На testnet можно использовать тестовые кошельки для получения JWT токена.
    """
    
    @pytest.mark.asyncio
    async def test_get_my_orders_no_auth(self, test_client):
        """
        Тест получения ордеров без аутентификации.
        
        Должен вернуть ошибку или пустой список, так как нет JWT токена.
        На testnet без JWT токена метод вернет 401 или пустой список.
        """
        # На testnet без JWT токена метод должен вернуть пустой список или ошибку
        orders, cursor = await test_client.get_my_orders()
        
        # Может вернуть пустой список или None в зависимости от реализации
        assert isinstance(orders, list)
    
    @pytest.mark.asyncio
    async def test_get_my_orders_with_auth(self, authenticated_client):
        """
        Тест получения ордеров с аутентификацией.
        
        Использует credentials из переменных TEST_PREDICT_ACCOUNT_ADDRESS и TEST_PRIVY_WALLET_PRIVATE_KEY.
        Если credentials не установлены, тест пропускается.
        """
        if authenticated_client is None:
            pytest.skip("Требуются тестовые credentials (TEST_PREDICT_ACCOUNT_ADDRESS, TEST_PRIVY_WALLET_PRIVATE_KEY)")
        
        orders, cursor = await authenticated_client.get_my_orders()
        assert isinstance(orders, list)
    
    @pytest.mark.asyncio
    async def test_get_my_orders_with_filters(self, test_client):
        """Тест получения ордеров с фильтрами."""
        orders, cursor = await test_client.get_my_orders(
            first=10,
            status='OPEN'
        )
        
        assert isinstance(orders, list)
    
    @pytest.mark.asyncio
    async def test_get_positions(self, authenticated_client):
        """
        Тест получения позиций.
        
        Использует credentials из переменных TEST_PREDICT_ACCOUNT_ADDRESS и TEST_PRIVY_WALLET_PRIVATE_KEY.
        Если credentials не установлены, тест пропускается.
        """
        if authenticated_client is None:
            pytest.skip("Требуются тестовые credentials (TEST_PREDICT_ACCOUNT_ADDRESS, TEST_PRIVY_WALLET_PRIVATE_KEY)")
        
        positions, cursor = await authenticated_client.get_positions(first=10)
        assert isinstance(positions, list)
    
    @pytest.mark.asyncio
    async def test_get_account(self, authenticated_client):
        """
        Тест получения информации об аккаунте.
        
        Использует credentials из переменных TEST_PREDICT_ACCOUNT_ADDRESS и TEST_PRIVY_WALLET_PRIVATE_KEY.
        Если credentials не установлены, тест пропускается.
        """
        if authenticated_client is None:
            pytest.skip("Требуются тестовые credentials (TEST_PREDICT_ACCOUNT_ADDRESS, TEST_PRIVY_WALLET_PRIVATE_KEY)")
        
        account = await authenticated_client.get_account()
        
        if account:
            assert isinstance(account, dict)
            assert 'address' in account or 'name' in account
    
    @pytest.mark.asyncio
    # @pytest.mark.skip(reason="Требует OrderBuilder из SDK и баланс USDT на тестовом кошельке")
    async def test_place_order(self, authenticated_client):
        """
        Тест размещения ордера.
        
        Требует:
        1. Реальные тестовые credentials (устанавливаются через TEST_PREDICT_ACCOUNT_ADDRESS, TEST_PRIVY_WALLET_PRIVATE_KEY)
        2. OrderBuilder из predict-sdk для создания подписанного ордера
        3. Данные рынка (market_id, token_id, feeRateBps) - получаются с testnet
        4. Баланс USDT на тестовом Predict Account
        
        Для тестирования:
        1. Установите TEST_PREDICT_ACCOUNT_ADDRESS и TEST_PRIVY_WALLET_PRIVATE_KEY
        2. Получите тестовые USDT на Predict Account
        3. Убедитесь, что на Privy Wallet есть BNB для газа (если нужно)
        """
        if authenticated_client is None:
            pytest.skip("Требуются тестовые credentials (TEST_PREDICT_ACCOUNT_ADDRESS, TEST_PRIVY_WALLET_PRIVATE_KEY)")
        
        # Создаем OrderBuilder с учетом типа кошелька
        chain_id = get_chain_id()
        
        try:
            # Создаем OrderBuilder для Predict Account
            signer: LocalAccount = Account.from_key(ACTUAL_PRIVATE_KEY)
            order_builder = OrderBuilder.make(
                chain_id,
                signer,
                OrderBuilderOptions(predict_account=ACTUAL_WALLET_ADDRESS)
            )
        except InvalidSignerError as e:
            pytest.skip(
                f"Приватный ключ не является владельцем Predict Account. "
                f"Возможные причины:\n"
                f"1. TEST_PRIVY_WALLET_PRIVATE_KEY не соответствует Predict Account {ACTUAL_WALLET_ADDRESS}\n"
                f"2. Predict Account создан на другой сети (mainnet vs testnet)\n"
                f"3. Неверный адрес Predict Account\n\n"
                f"Решение:\n"
                f"- Убедитесь, что используете правильный Privy Wallet private key из настроек: https://predict.fun/account/settings\n"
                f"- Проверьте, что Predict Account существует на {chain_id.name}\n"
                f"- Для testnet может потребоваться создать новый Predict Account или использовать EOA кошелек"
            )
        
        # Получаем данные рынка
        markets, _ = await authenticated_client.get_markets(first=1)
        if not markets:
            pytest.skip("Нет доступных рынков на testnet")
        
        market = markets[0]
        token_id = market['outcomes'][0]['onChainId']
        fee_rate_bps = market['feeRateBps']
        
        # Размещаем ордер через SDK + REST API
        # Шаг 1: Строим и подписываем ордер через SDK
        signed_order_data = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id=token_id,
            price_per_share_wei=500000000000000000,  # 0.5 USDT
            quantity_wei=10000000000000000000,  # 10 shares
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=market['isNegRisk'],
            is_yield_bearing=market['isYieldBearing']
        )
        
        assert signed_order_data is not None
        
        # Шаг 2: Размещаем ордер через REST API
        result = await authenticated_client.place_order(
            order=signed_order_data['order'],
            price_per_share=signed_order_data['pricePerShare'],
            strategy="LIMIT"
        )
        
        assert result is not None


class TestOrderMethods:
    """Тесты для методов работы с ордерами."""
    
    @pytest.mark.asyncio
    async def test_cancel_orders_empty_list(self, test_client):
        """Тест отмены пустого списка ордеров."""
        result = await test_client.cancel_orders([])
        
        assert isinstance(result, dict)
        assert result.get('success') == False
        assert result.get('removed') == []
        assert result.get('noop') == []
    
class TestErrorHandling:
    """Тесты обработки ошибок."""
    
    @pytest.mark.asyncio
    async def test_get_market_invalid_id(self, test_client):
        """Тест получения несуществующего рынка."""
        market = await test_client.get_market(999999999)
        
        # Должен вернуть None для несуществующего рынка
        assert market is None
    
    @pytest.mark.asyncio
    async def test_get_orderbook_invalid_id(self, test_client):
        """Тест получения orderbook для несуществующего рынка."""
        orderbook = await test_client.get_orderbook(999999999)
        
        # Должен вернуть None для несуществующего рынка
        assert orderbook is None
    
    @pytest.mark.asyncio
    async def test_get_order_by_id_invalid_hash(self, test_client):
        """Тест получения ордера по несуществующему hash."""
        order = await test_client.get_order_by_id("0xinvalid")
        
        # Должен вернуть None для несуществующего ордера
        assert order is None


class TestClientInitialization:
    """Тесты инициализации клиента."""
    
    def test_client_init(self):
        """Тест создания клиента."""
        client = PredictAPIClient(
            api_key="test_key",
            wallet_address="0x123",
            private_key="0x456"
        )
        
        assert client.api_key == "test_key"
        assert client.wallet_address == "0x123"
        assert client.private_key == "0x456"
        assert client.jwt_token is None


class TestAPIBaseURL:
    """Тесты для проверки использования правильного API URL."""
    
    def test_api_base_url_testnet(self):
        """Проверка, что используется testnet URL."""
        # Убеждаемся, что TEST_MODE установлен
        os.environ['TEST_MODE'] = 'true'
        
        api_url = get_api_base_url()
        
        assert 'testnet' in api_url or 'test' in api_url.lower()
        assert api_url.endswith('/v1')
    
    def test_api_base_url_custom(self):
        """Проверка использования кастомного URL."""
        custom_url = "https://custom-api.test.com/v1"
        os.environ['API_BASE_URL_TEST'] = custom_url
        os.environ['TEST_MODE'] = 'true'
        
        api_url = get_api_base_url()
        
        assert api_url == custom_url


@pytest.mark.asyncio
class TestIntegration:
    """Интеграционные тесты с реальным testnet API."""
    
    async def test_full_flow_get_market_and_orderbook(self, test_client):
        """Полный flow: получение рынка и его orderbook."""
        # Шаг 1: Получаем список рынков
        markets, _ = await test_client.get_markets(first=1)
        
        if not markets:
            pytest.skip("Нет доступных рынков на testnet")
        
        market_id = markets[0]['id']
        
        # Шаг 2: Получаем детали рынка
        market = await test_client.get_market(market_id)
        assert market is not None
        assert market['id'] == market_id
        
        # Шаг 3: Получаем orderbook
        orderbook = await test_client.get_orderbook(market_id)
        # Orderbook может быть None если нет ордеров
        if orderbook:
            assert orderbook['marketId'] == market_id
    
    async def test_pagination_flow(self, test_client):
        """Тест полного flow пагинации."""
        # Получаем первую страницу
        markets1, cursor1 = await test_client.get_markets(first=5)
        assert len(markets1) <= 5
        
        # Если есть cursor, получаем вторую страницу
        if cursor1:
            markets2, cursor2 = await test_client.get_markets(first=5, after=cursor1)
            assert isinstance(markets2, list)
            
            # Проверяем, что это разные страницы (если есть достаточно данных)
            if len(markets1) == 5 and len(markets2) > 0:
                assert markets1[0]['id'] != markets2[0]['id']

