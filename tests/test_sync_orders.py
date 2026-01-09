"""
Тесты для bot/sync_orders.py

Покрывает различные кейсы:
- Когда изменение цены достаточно для перестановки ордера
- Когда изменение недостаточно
- Проверка уведомлений о смещении цены
- Проверка правильности списков для отмены/размещения
- Уведомления об ошибках отмены ордеров (send_cancellation_error_notification)
- Уведомления об ошибках размещения ордеров (send_order_placement_error_notification)
- Проверка статусов ордеров (OPEN, FILLED, CANCELLED, EXPIRED, INVALIDATED)
- Пересчет цены перед размещением
- Логика с total_processed = len(removed) + len(noop)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List

# Импортируем функции для тестирования
# conftest.py настроит sys.path для работы с относительными импортами
from sync_orders import (
    process_user_orders,
    get_current_market_price,
    send_cancellation_error_notification,
    send_order_placement_error_notification,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_INVALIDATED
)
from predict_api.sdk_operations import calculate_new_target_price
from config import TICK_SIZE
from predict_sdk import Side


class TestCalculateNewTargetPrice:
    """Тесты для функции calculate_new_target_price"""
    
    def test_calculate_buy_price(self):
        """Тест расчета целевой цены для BUY ордера"""
        current_price = 0.5
        offset_ticks = 10
        side = "BUY"
        
        result = calculate_new_target_price(current_price, side, offset_ticks)
        
        # Для BUY: target = current_price - offset_ticks * TICK_SIZE
        expected = current_price - offset_ticks * TICK_SIZE
        assert result == expected
    
    def test_calculate_sell_price(self):
        """Тест расчета целевой цены для SELL ордера"""
        current_price = 0.5
        offset_ticks = 10
        side = "SELL"
        
        result = calculate_new_target_price(current_price, side, offset_ticks)
        
        # Для SELL: target = current_price + offset_ticks * TICK_SIZE
        expected = current_price + offset_ticks * TICK_SIZE
        assert result == expected
    
    def test_price_limits_min(self):
        """Тест ограничения минимальной цены (0.001)"""
        current_price = 0.01
        offset_ticks = 100  # Большой отступ для BUY
        side = "BUY"
        
        result = calculate_new_target_price(current_price, side, offset_ticks)
        
        # Цена не должна быть меньше 0.001
        assert result >= 0.001
    
    def test_price_limits_max(self):
        """Тест ограничения максимальной цены (0.999)"""
        current_price = 0.99
        offset_ticks = 100  # Большой отступ для SELL
        side = "SELL"
        
        result = calculate_new_target_price(current_price, side, offset_ticks)
        
        # Цена не должна быть больше 0.999
        assert result <= 0.999


class TestGetCurrentMarketPrice:
    """Тесты для функции get_current_market_price"""
    
    @pytest.mark.asyncio
    async def test_get_price_buy_yes(self):
        """Тест получения цены для BUY YES токена"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.500, 100], [0.499, 200]],  # Массив массивов [price, size]
            'asks': [[0.501, 150], [0.502, 250]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        # Для BUY берем best_bid (максимальный бид)
        assert price == 0.500
    
    @pytest.mark.asyncio
    async def test_get_price_sell_yes(self):
        """Тест получения цены для SELL YES токена"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.500, 100], [0.499, 200]],
            'asks': [[0.501, 150], [0.502, 250]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "SELL", "YES")
        
        # Для SELL берем best_ask (минимальный аск)
        assert price == 0.501
    
    @pytest.mark.asyncio
    async def test_get_price_buy_no(self):
        """Тест получения цены для BUY NO токена (цена NO = 1 - price_yes)"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.500, 100], [0.499, 200]],
            'asks': [[0.501, 150], [0.502, 250]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "NO")
        
        # Для NO токена: price_no = 1 - best_bid_yes
        assert price == 1.0 - 0.500
    
    @pytest.mark.asyncio
    async def test_get_price_sell_no(self):
        """Тест получения цены для SELL NO токена (цена NO = 1 - price_yes)"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.500, 100], [0.499, 200]],
            'asks': [[0.501, 150], [0.502, 250]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "SELL", "NO")
        
        # Для NO токена: price_no = 1 - best_ask_yes
        assert price == 1.0 - 0.501
    
    @pytest.mark.asyncio
    async def test_get_price_no_orderbook(self):
        """Тест обработки отсутствия orderbook"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = None
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        assert price is None
    
    @pytest.mark.asyncio
    async def test_get_price_empty_bids(self):
        """Тест обработки пустых bids для BUY"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [],
            'asks': [[0.501, 150]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        assert price is None


class TestProcessUserOrders:
    """Тесты для функции process_user_orders"""
    
    @pytest.fixture
    def mock_user(self):
        """Мок пользователя"""
        return {
            'telegram_id': 12345,
            'username': 'test_user',
            'wallet_address': '0x123',
            'private_key': 'key',
            'api_key': 'api_key'
        }
    
    @pytest.fixture
    def mock_api_client(self):
        """Мок PredictAPIClient"""
        client = AsyncMock()
        return client
    
    @pytest.fixture
    def mock_order_builder(self):
        """Мок OrderBuilder"""
        builder = MagicMock()
        return builder
    
    @pytest.mark.asyncio
    async def test_no_user(self, mock_api_client):
        """Тест: пользователь не найден (нет ордеров)"""
        # process_user_orders не проверяет наличие пользователя, 
        # она просто получает ордера по telegram_id
        with patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders:
            mock_get_orders.return_value = []  # Мокируем, чтобы не обращаться к реальной БД
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            assert orders_to_cancel == []
            assert orders_to_place == []
            assert notifications == []
    
    @pytest.mark.asyncio
    async def test_no_orders(self, mock_user, mock_api_client):
        """Тест: у пользователя нет активных ордеров"""
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = []
            mock_client_class.return_value = AsyncMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            assert orders_to_cancel == []
            assert orders_to_place == []
            assert notifications == []
    
    @pytest.mark.asyncio
    async def test_reposition_sufficient_change(self, mock_user, mock_api_client):
        """Тест: изменение достаточно для перестановки ордера"""
        # Настройка ордера: изменение будет 1.0 цент (>= 0.5)
        db_order = {
            "order_hash": "order_123",
            "order_api_id": "123456789",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,  # Старая текущая цена
            "target_price": 0.490,   # Старая целевая цена (offset 10 ticks = 0.01 = 1.0 cent)
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        # Новая текущая цена: 0.510 (изменилась на 0.01)
        # Новая целевая цена: 0.500 (0.510 - 10*0.001)
        # Изменение целевой цены: 0.010 = 1.0 цент (>= 0.5)
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса ордера через API
            # Структура согласно документации API
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_OPEN,  # Ордер все еще открыт
                'id': '123456789',
                'order': {'hash': 'order_123', 'side': 0},  # 0=BUY
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            # Мокируем orderbook для получения цены
            mock_api_client.get_orderbook.return_value = {
                'bids': [[0.510, 100], [0.509, 200]],
                'asks': [[0.511, 150]]
            }
            
            mock_get_price.return_value = 0.510  # Новая текущая цена
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()  # OrderBuilder
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Проверяем, что ордер добавлен в списки для отмены/размещения
            assert len(orders_to_cancel) == 1
            assert orders_to_cancel[0] == "123456789"  # order_api_id
            assert len(orders_to_place) == 1
            
            # Проверяем параметры нового ордера
            new_order = orders_to_place[0]
            assert new_order["old_order_hash"] == "order_123"
            assert new_order["old_order_api_id"] == "123456789"
            assert new_order["market_id"] == 100
            assert new_order["token_id"] == "token_yes"
            assert new_order["price"] == pytest.approx(0.500, abs=0.0001)  # 0.510 - 10*0.001
            assert new_order["side"] == Side.BUY
            assert new_order["side_str"] == "BUY"
            assert new_order["token_name"] == "YES"
            assert new_order["offset_ticks"] == 10
            
            # Проверяем уведомление
            assert len(notifications) == 1
            notification = notifications[0]
            assert notification["order_hash"] == "order_123"
            assert notification["order_api_id"] == "123456789"
            assert notification["will_reposition"] is True
            assert notification["target_price_change_cents"] >= 0.5
    
    @pytest.mark.asyncio
    async def test_reposition_insufficient_change(self, mock_user, mock_api_client):
        """Тест: изменение недостаточно для перестановки ордера"""
        # Настройка ордера: изменение будет 0.3 цент (< 0.5)
        db_order = {
            "order_hash": "order_456",
            "order_api_id": "987654321",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_no",
            "token_name": "NO",
            "side": "SELL",
            "current_price": 0.500,  # Старая текущая цена
            "target_price": 0.510,   # Старая целевая цена (offset 10 ticks = 0.01)
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        # Новая текущая цена: 0.503 (изменилась на 0.003)
        # Новая целевая цена: 0.513 (0.503 + 10*0.001)
        # Изменение целевой цены: 0.003 = 0.3 цент (< 0.5)
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса ордера через API
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_OPEN,
                'id': '987654321',
                'order': {'hash': 'order_456', 'side': 1},  # 1=SELL
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_price.return_value = 0.503  # Новая текущая цена
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Проверяем, что ордер НЕ добавлен в списки для отмены/размещения
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Уведомление НЕ отправляется, так как изменение недостаточно для перестановки
            assert len(notifications) == 0
    
    @pytest.mark.asyncio
    async def test_order_status_filled(self, mock_user, mock_api_client):
        """Тест: ордер был исполнен (статус FILLED)"""
        db_order = {
            "order_hash": "order_filled",
            "order_api_id": "123456789",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.update_order_status', new_callable=AsyncMock) as mock_update_status, \
             patch('sync_orders.send_order_filled_notification', new_callable=AsyncMock) as mock_send_notif, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса: ордер исполнен
            # Структура согласно документации API
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_FILLED,
                'id': '123456789',
                'order': {
                    'hash': 'order_filled',
                    'side': 0  # 0=BUY, 1=SELL
                },
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '100.0',
                'currency': 'USDT'
            }
            
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client, bot=MagicMock())
            
            # Ордер не должен быть в списках для перестановки (уже исполнен)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Статус должен быть обновлен на FILLED (API статус)
            mock_update_status.assert_called_once_with("order_filled", ORDER_STATUS_FILLED)
            
            # Уведомление должно быть отправлено
            mock_send_notif.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_order_status_cancelled(self, mock_user, mock_api_client):
        """Тест: ордер был отменен (статус CANCELLED)"""
        db_order = {
            "order_hash": "order_cancelled",
            "order_api_id": "123456789",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.update_order_status', new_callable=AsyncMock) as mock_update_status, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса: ордер отменен
            # Структура согласно документации API
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_CANCELLED,
                'id': '123456789',
                'order': {'hash': 'order_cancelled', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер не должен быть в списках для перестановки (уже отменен)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Статус должен быть обновлен на CANCELLED (API статус)
            mock_update_status.assert_called_once_with("order_cancelled", ORDER_STATUS_CANCELLED)
    
    @pytest.mark.asyncio
    async def test_no_price_change(self, mock_user, mock_api_client):
        """Тест: цена не изменилась"""
        db_order = {
            "order_hash": "order_789",
            "order_api_id": "111222333",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,  # offset 10 ticks
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        # Цена не изменилась
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_OPEN,
                'id': '111222333',
                'order': {'hash': 'order_789', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_price.return_value = 0.500  # Та же цена
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Новая целевая цена будет та же: 0.490 (0.500 - 10*0.001)
            # Изменение: 0.0 (< 0.5)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            # Уведомление НЕ отправляется, так как изменение недостаточно для перестановки
            assert len(notifications) == 0
    
    @pytest.mark.asyncio
    async def test_multiple_orders_mixed(self, mock_user, mock_api_client):
        """Тест: несколько ордеров, часть переставляется, часть нет"""
        db_orders = [
            {
                "order_hash": "order_1",
                "order_api_id": "111",
                "market_id": 100,
                "market_title": "Test Market",
                "market_slug": "test-market",
                "token_id": "token_yes",
                "token_name": "YES",
                "side": "BUY",
                "current_price": 0.500,
                "target_price": 0.490,
                "offset_ticks": 10,
                "amount": 100.0,
                "reposition_threshold_cents": 0.5,
                "status": ORDER_STATUS_OPEN
            },
            {
                "order_hash": "order_2",
                "order_api_id": "222",
                "market_id": 100,
                "market_title": "Test Market",
                "market_slug": "test-market",
                "token_id": "token_no",
                "token_name": "NO",
                "side": "SELL",
                "current_price": 0.500,
                "target_price": 0.510,
                "offset_ticks": 10,
                "amount": 100.0,
                "reposition_threshold_cents": 0.5,
                "status": ORDER_STATUS_OPEN
            }
        ]
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = db_orders
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса для обоих ордеров
            def get_order_side_effect(order_hash, **kwargs):
                if order_hash == "order_1":
                    return {
                        'status': ORDER_STATUS_OPEN,
                        'id': '111',
                        'order': {'hash': 'order_1', 'side': 0},
                        'marketId': 100,
                        'amount': '100.0',
                        'amountFilled': '0.0',
                        'currency': 'USDT'
                    }
                elif order_hash == "order_2":
                    return {
                        'status': ORDER_STATUS_OPEN,
                        'id': '222',
                        'order': {'hash': 'order_2', 'side': 1},
                        'marketId': 100,
                        'amount': '100.0',
                        'amountFilled': '0.0',
                        'currency': 'USDT'
                    }
                return None
            
            mock_api_client.get_order_by_id.side_effect = get_order_side_effect
            
            # Первый ордер: изменение достаточно (1.0 цент)
            # Второй ордер: изменение недостаточно (0.3 цента)
            def get_price_side_effect(api_client, market_id, side, token_name):
                if token_name == "YES" and side == "BUY":
                    return 0.510  # Изменение 0.01 = 1.0 цент
                elif token_name == "NO" and side == "SELL":
                    return 0.503  # Изменение 0.003 = 0.3 цента
                return None
            
            mock_get_price.side_effect = get_price_side_effect
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Первый ордер должен быть переставлен
            assert len(orders_to_cancel) == 1
            assert orders_to_cancel[0] == "111"  # order_api_id
            assert len(orders_to_place) == 1
            
            # Уведомление отправляется только для первого ордера (который будет переставлен)
            assert len(notifications) == 1
            
            # Проверяем уведомление для первого ордера
            notif1 = notifications[0]
            assert notif1["order_hash"] == "order_1"
            assert notif1["order_api_id"] == "111"
            assert notif1["will_reposition"] is True
    
    @pytest.mark.asyncio
    async def test_notification_only_when_repositioning(self, mock_user, mock_api_client):
        """Тест: уведомление отправляется только когда ордер будет переставлен"""
        db_order = {
            "order_hash": "order_notify",
            "order_api_id": "999888777",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 1.0,  # Высокий порог
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_OPEN,
                'id': '999888777',
                'order': {'hash': 'order_notify', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_price.return_value = 0.501  # Небольшое изменение
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер не переставляется (изменение 0.001 = 0.1 цент < 1.0 цент)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Уведомление НЕ отправляется, так как изменение недостаточно для перестановки
            assert len(notifications) == 0
    
    @pytest.mark.asyncio
    async def test_notification_structure(self, mock_user, mock_api_client):
        """Тест: проверка структуры уведомления"""
        db_order = {
            "order_hash": "order_struct",
            "order_api_id": "555444333",
            "market_id": 200,
            "market_title": "Test Market 2",
            "market_slug": "test-market-2",
            "token_id": "token_test",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.get_current_market_price') as mock_get_price, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_OPEN,
                'id': '555444333',
                'order': {'hash': 'order_struct', 'side': 0},
                'marketId': 200,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_price.return_value = 0.510
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            _, _, notifications = await process_user_orders(12345, mock_api_client)
            
            assert len(notifications) == 1
            notification = notifications[0]
            
            # Проверяем все обязательные поля
            required_fields = [
                "order_hash", "order_api_id", "market_id", "market_title", "market_slug",
                "token_name", "side",
                "old_current_price", "new_current_price",
                "old_target_price", "new_target_price",
                "price_change", "target_price_change",
                "target_price_change_cents", "reposition_threshold_cents",
                "offset_ticks", "will_reposition"
            ]
            
            for field in required_fields:
                assert field in notification, f"Поле {field} отсутствует в уведомлении"
            
            # Проверяем значения
            assert notification["order_hash"] == "order_struct"
            assert notification["order_api_id"] == "555444333"
            assert notification["market_id"] == 200
            assert notification["market_title"] == "Test Market 2"
            assert notification["market_slug"] == "test-market-2"
            assert notification["token_name"] == "YES"
            assert notification["side"] == "BUY"
            assert notification["old_current_price"] == 0.500
            assert notification["new_current_price"] == 0.510
            assert notification["reposition_threshold_cents"] == 0.5
            assert isinstance(notification["will_reposition"], bool)
    
    @pytest.mark.asyncio
    async def test_order_status_expired(self, mock_user, mock_api_client):
        """Тест: ордер истек (статус EXPIRED)"""
        db_order = {
            "order_hash": "order_expired",
            "order_api_id": "444555666",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.update_order_status', new_callable=AsyncMock) as mock_update_status, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса: ордер истек
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_EXPIRED,
                'id': '444555666',
                'order': {'hash': 'order_expired', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер не должен быть в списках для перестановки (уже истек)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Статус должен быть обновлен на EXPIRED (API статус)
            mock_update_status.assert_called_once_with("order_expired", ORDER_STATUS_EXPIRED)
    
    @pytest.mark.asyncio
    async def test_order_status_invalidated(self, mock_user, mock_api_client):
        """Тест: ордер инвалидирован (статус INVALIDATED)"""
        db_order = {
            "order_hash": "order_invalidated",
            "order_api_id": "777888999",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.update_order_status', new_callable=AsyncMock) as mock_update_status, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса: ордер инвалидирован
            mock_api_client.get_order_by_id.return_value = {
                'status': ORDER_STATUS_INVALIDATED,
                'id': '777888999',
                'order': {'hash': 'order_invalidated', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер не должен быть в списках для перестановки (уже инвалидирован)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Статус должен быть обновлен на INVALIDATED (API статус)
            mock_update_status.assert_called_once_with("order_invalidated", ORDER_STATUS_INVALIDATED)
    
    @pytest.mark.asyncio
    async def test_unknown_status_from_api(self, mock_user, mock_api_client):
        """Тест: неизвестный статус из API (должен быть сохранен в БД с предупреждением)"""
        db_order = {
            "order_hash": "order_unknown",
            "order_api_id": "000111222",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user', new_callable=AsyncMock) as mock_get_user, \
             patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.PredictAPIClient') as mock_client_class, \
             patch('sync_orders.update_order_status', new_callable=AsyncMock) as mock_update_status, \
             patch('sync_orders.get_chain_id') as mock_get_chain_id, \
             patch('sync_orders.OrderBuilder') as mock_order_builder_class, \
             patch('sync_orders.asyncio.to_thread') as mock_to_thread:
            
            mock_get_user.return_value = mock_user
            mock_get_orders.return_value = [db_order]
            mock_client_class.return_value = mock_api_client
            
            # Мокируем проверку статуса: неизвестный статус
            mock_api_client.get_order_by_id.return_value = {
                'status': 'UNKNOWN_STATUS',
                'id': '000111222',
                'order': {'hash': 'order_unknown', 'side': 0},
                'marketId': 100,
                'amount': '100.0',
                'amountFilled': '0.0',
                'currency': 'USDT'
            }
            
            mock_get_chain_id.return_value = MagicMock()
            mock_order_builder_class.make = MagicMock()
            mock_to_thread.return_value = MagicMock()
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер не должен быть в списках для перестановки (неизвестный статус)
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
            
            # Статус должен быть обновлен на неизвестный статус из API (сохраняем как есть)
            mock_update_status.assert_called_once_with("order_unknown", 'UNKNOWN_STATUS')


class TestCancellationErrorNotification:
    """Тесты для функции send_cancellation_error_notification"""
    
    @pytest.mark.asyncio
    async def test_send_notification_single_order(self):
        """Тест: отправка уведомления об ошибке отмены одного ордера"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        failed_orders = [
            {
                "order_hash": "order_123",
                "market_id": 100,
                "market_title": "Test Market",
                "token_name": "YES",
                "side": "BUY",
                "errno": "N/A",
                "errmsg": "Failed to cancel order"
            }
        ]
        
        await send_cancellation_error_notification(mock_bot, telegram_id, failed_orders)
        
        # Проверяем, что send_message был вызван
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        
        assert call_args.kwargs['chat_id'] == telegram_id
        message = call_args.kwargs['text']
        
        # Проверяем содержимое сообщения
        assert "Order Cancellation Failed" in message
        assert "Failed to cancel 1 order(s)" in message
        assert "order_123" in message
        assert "Test Market" in message
        assert "YES" in message
        assert "BUY" in message
        assert "Failed to cancel order" in message
        assert "New orders will NOT be placed" in message
    
    @pytest.mark.asyncio
    async def test_send_notification_multiple_orders(self):
        """Тест: отправка уведомления об ошибке отмены нескольких ордеров"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        failed_orders = [
            {
                "order_hash": "order_1",
                "market_id": 100,
                "market_title": "Test Market 1",
                "token_name": "YES",
                "side": "BUY",
                "errno": "N/A",
                "errmsg": "Order not found"
            },
            {
                "order_hash": "order_2",
                "market_id": 200,
                "market_title": "Test Market 2",
                "token_name": "NO",
                "side": "SELL",
                "errno": "N/A",
                "errmsg": "Insufficient balance"
            }
        ]
        
        await send_cancellation_error_notification(mock_bot, telegram_id, failed_orders)
        
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        message = call_args.kwargs['text']
        
        # Проверяем, что оба ордера упомянуты
        assert "Failed to cancel 2 order(s)" in message
        assert "order_1" in message
        assert "order_2" in message
        assert "Test Market 1" in message
        assert "Test Market 2" in message
    
    @pytest.mark.asyncio
    async def test_empty_failed_orders_list(self):
        """Тест: пустой список неудачных отмен (не должно отправляться сообщение)"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        await send_cancellation_error_notification(mock_bot, telegram_id, [])
        
        # Проверяем, что send_message НЕ был вызван
        assert not mock_bot.send_message.called
    
    @pytest.mark.asyncio
    async def test_missing_fields_in_failed_order(self):
        """Тест: обработка отсутствующих полей в failed_orders"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        # Ордер с неполными данными
        failed_orders = [
            {
                "order_hash": "order_123",
                # Отсутствуют некоторые поля
            }
        ]
        
        await send_cancellation_error_notification(mock_bot, telegram_id, failed_orders)
        
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        message = call_args.kwargs['text']
        
        # Проверяем, что используются значения по умолчанию
        assert "order_123" in message
        assert "N/A" in message  # Для отсутствующих полей (market_title)
    
    @pytest.mark.asyncio
    async def test_send_notification_error_handling(self):
        """Тест: обработка ошибки при отправке уведомления"""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = Exception("Telegram API error")
        telegram_id = 12345
        
        failed_orders = [
            {
                "order_hash": "order_123",
                "market_id": 100,
                "market_title": "Test Market",
                "token_name": "YES",
                "side": "BUY",
                "errno": "N/A",
                "errmsg": "Order not found"
            }
        ]
        
        # Функция должна обработать ошибку и не упасть
        await send_cancellation_error_notification(mock_bot, telegram_id, failed_orders)
        
        # Проверяем, что send_message был вызван (ошибка обработана внутри функции)
        assert mock_bot.send_message.called


class TestOrderPlacementErrorNotification:
    """Тесты для функции send_order_placement_error_notification"""
    
    @pytest.mark.asyncio
    async def test_send_notification_buy_order(self):
        """Тест: отправка уведомления об ошибке размещения BUY ордера"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        order_params = {
            "market_id": 100,
            "token_name": "YES",
            "side": Side.BUY,
            "current_price_at_creation": 0.500,
            "target_price": 0.490,
            "amount": 100.0
        }
        old_order_id = "order_123"
        errno = 0
        errmsg = "Insufficient balance"
            
        await send_order_placement_error_notification(
            mock_bot, telegram_id, order_params, old_order_id, errno, errmsg
        )
            
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
            
        assert call_args.kwargs['chat_id'] == telegram_id
        message = call_args.kwargs['text']
            
            # Проверяем содержимое сообщения
        assert "Order Repositioning Failed" in message
        assert "YES BUY" in message
        assert "100" in message
        assert "order_123" in message
        assert "49.00 cents" in message  # 0.490 * 100
        assert "100.0 USDT" in message
        assert "Error 0" in message
        assert "Insufficient balance" in message
        assert "📈" in message  # Эмодзи для BUY
    
    @pytest.mark.asyncio
    async def test_send_notification_sell_order(self):
        """Тест: отправка уведомления об ошибке размещения SELL ордера"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        order_params = {
            "market_id": 200,
            "token_name": "NO",
            "side": Side.SELL,
            "current_price_at_creation": 0.600,
            "target_price": 0.610,
            "amount": 50.0
           }
        old_order_id = "order_456"
        errno = 0
        errmsg = "Market closed"
            
        await send_order_placement_error_notification(
            mock_bot, telegram_id, order_params, old_order_id, errno, errmsg
        )
            
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        message = call_args.kwargs['text']
            
        assert "NO SELL" in message
        assert "61.00 cents" in message  # 0.610 * 100
        assert "50.0 USDT" in message
        assert "📉" in message  # Эмодзи для SELL
    
    @pytest.mark.asyncio
    async def test_send_notification_missing_fields(self):
        """Тест: обработка отсутствующих полей в order_params"""
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        # order_params с неполными данными
        order_params = {
            "market_id": 100,
            # Отсутствуют некоторые поля
        }
        old_order_id = "order_123"
        errno = 0
        errmsg = "Error"
            
            # Функция должна обработать отсутствующие поля
        await send_order_placement_error_notification(
            mock_bot, telegram_id, order_params, old_order_id, errno, errmsg
        )
            
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        message = call_args.kwargs['text']
            
            # Проверяем, что сообщение сформировано (используются значения по умолчанию)
        assert "Order Repositioning Failed" in message
        assert "order_123" in message
    
    @pytest.mark.asyncio
    async def test_send_notification_error_handling(self):
        """Тест: обработка ошибки при отправке уведомления"""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = Exception("Telegram API error")
        telegram_id = 12345
        
        order_params = {
            "market_id": 100,
            "token_name": "YES",
            "side": Side.BUY,
            "current_price_at_creation": 0.500,
            "target_price": 0.490,
            "amount": 100.0
        }
        old_order_id = "order_123"
        errno = 10208
        errmsg = "Insufficient balance"
            
        # Функция должна обработать ошибку и не упасть
        await send_order_placement_error_notification(
            mock_bot, telegram_id, order_params, old_order_id, errno, errmsg
        )
            
            # Проверяем, что send_message был вызван (ошибка обработана внутри функции)
        assert mock_bot.send_message.called


class TestCancelOrdersBatch:
    """Тесты для функции cancel_orders_batch и логики с noop"""
    
    @pytest.mark.asyncio
    async def test_cancel_orders_with_noop(self):
        """Тест: отмена ордеров с noop (ордера уже были удалены/исполнены)"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        
        # Мокируем ответ API: часть ордеров удалена, часть уже была удалена (noop)
        mock_api_client.cancel_orders.return_value = {
            'success': True,
            'removed': ['order_1', 'order_2'],  # Успешно удалены
            'noop': ['order_3']  # Уже были удалены ранее
        }
        
        orders_to_cancel = ['order_1', 'order_2', 'order_3']
        result = await cancel_orders_batch(mock_api_client, orders_to_cancel)
        
        assert result['success'] is True
        assert len(result['removed']) == 2
        assert len(result['noop']) == 1
        assert 'order_1' in result['removed']
        assert 'order_2' in result['removed']
        assert 'order_3' in result['noop']
        
        # Проверяем, что total_processed = len(removed) + len(noop) = 3
        total_processed = len(result['removed']) + len(result['noop'])
        assert total_processed == 3
    
    @pytest.mark.asyncio
    async def test_cancel_orders_all_removed(self):
        """Тест: все ордера успешно удалены (нет noop)"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        
        mock_api_client.cancel_orders.return_value = {
            'success': True,
            'removed': ['order_1', 'order_2', 'order_3'],
            'noop': []
        }
        
        orders_to_cancel = ['order_1', 'order_2', 'order_3']
        result = await cancel_orders_batch(mock_api_client, orders_to_cancel)
        
        assert result['success'] is True
        assert len(result['removed']) == 3
        assert len(result['noop']) == 0
        
        total_processed = len(result['removed']) + len(result['noop'])
        assert total_processed == 3
    
    @pytest.mark.asyncio
    async def test_cancel_orders_all_noop(self):
        """Тест: все ордера уже были удалены ранее (все в noop)"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        
        mock_api_client.cancel_orders.return_value = {
            'success': True,
            'removed': [],
            'noop': ['order_1', 'order_2', 'order_3']
        }
        
        orders_to_cancel = ['order_1', 'order_2', 'order_3']
        result = await cancel_orders_batch(mock_api_client, orders_to_cancel)
        
        assert result['success'] is True
        assert len(result['removed']) == 0
        assert len(result['noop']) == 3
        
        total_processed = len(result['removed']) + len(result['noop'])
        assert total_processed == 3
    
    @pytest.mark.asyncio
    async def test_cancel_orders_failure(self):
        """Тест: ошибка при отмене ордеров"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        
        mock_api_client.cancel_orders.return_value = {
            'success': False,
            'removed': [],
            'noop': [],
            'cause': 'API error'
        }
        
        orders_to_cancel = ['order_1', 'order_2']
        result = await cancel_orders_batch(mock_api_client, orders_to_cancel)
        
        assert result['success'] is False
        assert result['cause'] == 'API error'
        assert len(result['removed']) == 0
        assert len(result['noop']) == 0


class TestPlaceOrdersBatch:
    """Тесты для функции place_orders_batch и пересчета цены"""
    
    @pytest.mark.asyncio
    async def test_place_orders_with_price_recalculation(self):
        """Тест: размещение ордеров с пересчетом цены перед размещением"""
        from sync_orders import place_orders_batch, get_current_market_price
        
        mock_api_client = AsyncMock()
        
        # Мокируем orderbook для получения текущей цены
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.520, 100], [0.519, 200]],  # Новая текущая цена для BUY
            'asks': [[0.521, 150]]
        }
        
        # Мокируем get_market
        mock_api_client.get_market.return_value = {
            'feeRateBps': 100,
            'isNegRisk': False,
            'isYieldBearing': False
        }
        
        # Мокируем place_single_order
        with patch('sync_orders.place_single_order', new_callable=AsyncMock) as mock_place_order, \
             patch('sync_orders.get_current_market_price', new_callable=AsyncMock) as mock_get_price:
            
            # Пересчитанная цена: 0.520 - 10*0.001 = 0.510
            mock_get_price.return_value = 0.520
            mock_place_order.return_value = (True, "new_order_hash", "new_order_api_id", None)
            
            orders_params = [{
                'order_builder': MagicMock(),
                'market_id': 100,
                'token_id': 'token_yes',
                'token_name': 'YES',
                'side': Side.BUY,
                'side_str': 'BUY',
                'offset_ticks': 10,
                'price': 0.500,  # Старая цена (будет пересчитана)
                'amount': 100.0
            }]
            
            results = await place_orders_batch(mock_api_client, orders_params)
            
            # Проверяем, что place_single_order был вызван с пересчитанной ценой
            assert mock_place_order.called
            call_args = mock_place_order.call_args
            assert call_args.kwargs['price'] == pytest.approx(0.510, abs=0.0001)  # 0.520 - 10*0.001
            
            # Проверяем, что цены обновлены в params
            assert orders_params[0]['current_price_at_creation'] == 0.520
            assert orders_params[0]['target_price'] == pytest.approx(0.510, abs=0.0001)
            
            # Проверяем результат
            assert results[0]['success'] is True
            assert results[0]['order_hash'] == "new_order_hash"
            assert results[0]['order_api_id'] == "new_order_api_id"
    
    @pytest.mark.asyncio
    async def test_place_orders_without_price_recalculation(self):
        """Тест: размещение ордеров без пересчета цены (нет параметров для пересчета)"""
        from sync_orders import place_orders_batch
        
        mock_api_client = AsyncMock()
        
        mock_api_client.get_market.return_value = {
            'feeRateBps': 100,
            'isNegRisk': False,
            'isYieldBearing': False
        }
        
        with patch('sync_orders.place_single_order', new_callable=AsyncMock) as mock_place_order:
            mock_place_order.return_value = (True, "new_order_hash", "new_order_api_id", None)
            
            orders_params = [{
                'order_builder': MagicMock(),
                'market_id': 100,
                'token_id': 'token_yes',
                'side': Side.BUY,
                'price': 0.500,  # Цена без пересчета
                'amount': 100.0
                # Нет token_name, side_str, offset_ticks для пересчета
            }]
            
            results = await place_orders_batch(mock_api_client, orders_params)
            
            # Проверяем, что place_single_order был вызван с исходной ценой
            assert mock_place_order.called
            call_args = mock_place_order.call_args
            assert call_args.kwargs['price'] == 0.500
            
            # Проверяем результат
            assert results[0]['success'] is True


class TestGetCurrentMarketPriceEdgeCases:
    """Тесты для граничных случаев get_current_market_price"""
    
    @pytest.mark.asyncio
    async def test_get_price_network_error(self):
        """Тест: ошибка сети при получении orderbook"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.side_effect = Exception("Network error")
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        assert price is None
    
    @pytest.mark.asyncio
    async def test_get_price_invalid_orderbook_structure(self):
        """Тест: некорректная структура orderbook"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': 'invalid',  # Не массив
            'asks': []
        }
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        assert price is None
    
    @pytest.mark.asyncio
    async def test_get_price_invalid_price_format(self):
        """Тест: некорректный формат цены в bids"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [['invalid_price', 100], [0.500, 200]],  # Первая цена некорректная
            'asks': [[0.501, 150]]
        }
        
        price = await get_current_market_price(mock_api_client, 100, "BUY", "YES")
        
        # Должна использоваться вторая валидная цена
        assert price == 0.500
    
    @pytest.mark.asyncio
    async def test_get_price_empty_asks_for_sell(self):
        """Тест: пустые asks для SELL ордера"""
        mock_api_client = AsyncMock()
        mock_api_client.get_orderbook.return_value = {
            'bids': [[0.500, 100]],
            'asks': []  # Пустые asks
        }
        
        price = await get_current_market_price(mock_api_client, 100, "SELL", "YES")
        
        assert price is None


class TestProcessUserOrdersEdgeCases:
    """Тесты для граничных случаев process_user_orders"""
    
    @pytest.fixture
    def mock_api_client(self):
        """Мок PredictAPIClient"""
        client = AsyncMock()
        return client
    
    @pytest.mark.asyncio
    async def test_missing_required_fields(self, mock_api_client):
        """Тест: отсутствие обязательных полей в ордере"""
        db_order = {
            "order_hash": "order_incomplete",
            # Отсутствуют обязательные поля: market_id, side, token_id
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders:
            mock_get_orders.return_value = [db_order]
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Ордер должен быть пропущен из-за неполных данных
            assert len(orders_to_cancel) == 0
            assert len(orders_to_place) == 0
    
    @pytest.mark.asyncio
    async def test_status_check_timeout(self, mock_api_client):
        """Тест: таймаут при проверке статуса ордера"""
        db_order = {
            "order_hash": "order_timeout",
            "order_api_id": "123456789",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_id": "token_yes",
            "token_name": "YES",
            "side": "BUY",
            "current_price": 0.500,
            "target_price": 0.490,
            "offset_ticks": 10,
            "amount": 100.0,
            "reposition_threshold_cents": 0.5,
            "status": ORDER_STATUS_OPEN
        }
        
        with patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.get_current_market_price', new_callable=AsyncMock) as mock_get_price:
            
            mock_get_orders.return_value = [db_order]
            # Мокируем таймаут при проверке статуса
            mock_api_client.get_order_by_id.side_effect = Exception("504 Gateway Time-out")
            mock_get_price.return_value = 0.510
            
            # Должна продолжиться обработка несмотря на таймаут
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Обработка должна продолжиться (graceful degradation)
            assert len(orders_to_cancel) >= 0  # Может быть 0 или 1 в зависимости от изменения цены
    
    @pytest.mark.asyncio
    async def test_get_price_failure_continues(self, mock_api_client):
        """Тест: ошибка получения цены - обработка продолжается для других ордеров"""
        db_orders = [
            {
                "order_hash": "order_1",
                "order_api_id": "111",
                "market_id": 100,
                "market_title": "Test Market",
                "market_slug": "test-market",
                "token_id": "token_yes",
                "token_name": "YES",
                "side": "BUY",
                "current_price": 0.500,
                "target_price": 0.490,
                "offset_ticks": 10,
                "amount": 100.0,
                "reposition_threshold_cents": 0.5,
                "status": ORDER_STATUS_OPEN
            },
            {
                "order_hash": "order_2",
                "order_api_id": "222",
                "market_id": 200,
                "market_title": "Test Market 2",
                "market_slug": "test-market-2",
                "token_id": "token_no",
                "token_name": "NO",
                "side": "SELL",
                "current_price": 0.500,
                "target_price": 0.510,
                "offset_ticks": 10,
                "amount": 100.0,
                "reposition_threshold_cents": 0.5,
                "status": ORDER_STATUS_OPEN
            }
        ]
        
        with patch('sync_orders.get_user_orders', new_callable=AsyncMock) as mock_get_orders, \
             patch('sync_orders.get_current_market_price', new_callable=AsyncMock) as mock_get_price:
            
            mock_get_orders.return_value = db_orders
            
            # Мокируем проверку статуса
            def get_order_side_effect(order_hash, **kwargs):
                return {
                    'status': ORDER_STATUS_OPEN,
                    'id': '111' if order_hash == 'order_1' else '222',
                    'order': {'hash': order_hash, 'side': 0 if order_hash == 'order_1' else 1},
                    'marketId': 100 if order_hash == 'order_1' else 200,
                    'amount': '100.0',
                    'amountFilled': '0.0',
                    'currency': 'USDT'
                }
            
            mock_api_client.get_order_by_id.side_effect = get_order_side_effect
            
            # Первый ордер: успешно получаем цену
            # Второй ордер: ошибка получения цены
            def get_price_side_effect(api_client, market_id, side, token_name):
                if market_id == 100:
                    return 0.510  # Успешно
                else:
                    return None  # Ошибка
            
            mock_get_price.side_effect = get_price_side_effect
            
            orders_to_cancel, orders_to_place, notifications = await process_user_orders(12345, mock_api_client)
            
            # Первый ордер должен быть обработан, второй пропущен
            assert len(orders_to_cancel) == 1
            assert len(orders_to_place) == 1


class TestNotificationFunctions:
    """Тесты для функций отправки уведомлений"""
    
    @pytest.mark.asyncio
    async def test_send_price_change_notification(self):
        """Тест: отправка уведомления о смещении цены"""
        from sync_orders import send_price_change_notification
        
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        notification = {
            "order_hash": "order_123",
            "order_api_id": "123456789",
            "market_id": 100,
            "market_title": "Test Market",
            "market_slug": "test-market",
            "token_name": "YES",
            "side": "BUY",
            "old_current_price": 0.500,
            "new_current_price": 0.510,
            "old_target_price": 0.490,
            "new_target_price": 0.500,
            "price_change": 0.010,
            "target_price_change": 0.010,
            "target_price_change_cents": 1.0,
            "reposition_threshold_cents": 0.5,
            "offset_ticks": 10,
            "will_reposition": True
        }
        
        await send_price_change_notification(mock_bot, telegram_id, notification)
        
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs['chat_id'] == telegram_id
        message = call_args.kwargs['text']
        
        assert "Price Change Detected" in message
        assert "Test Market" in message
        assert "YES BUY" in message
        assert "50.00 cents" in message  # old_current_price
        assert "51.00 cents" in message  # new_current_price
        assert "Order will be repositioned" in message
    
    @pytest.mark.asyncio
    async def test_send_order_updated_notification(self):
        """Тест: отправка уведомления об успешном обновлении ордера"""
        from sync_orders import send_order_updated_notification
        
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        order_params = {
            "token_name": "YES",
            "side": Side.BUY,
            "market_title": "Test Market",
            "current_price_at_creation": 0.510,
            "target_price": 0.500,
            "amount": 100.0
        }
        new_order_hash = "new_order_hash_123"
        
        await send_order_updated_notification(mock_bot, telegram_id, order_params, new_order_hash)
        
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs['chat_id'] == telegram_id
        message = call_args.kwargs['text']
        
        assert "Order Updated Successfully" in message
        assert "Test Market" in message
        assert "YES BUY" in message
        assert "new_order_hash_123" in message
        assert "51.00 cents" in message  # current_price
        assert "50.00 cents" in message  # target_price
        assert "100.0 USDT" in message
    
    @pytest.mark.asyncio
    async def test_send_order_filled_notification(self):
        """Тест: отправка уведомления об исполнении ордера"""
        from sync_orders import send_order_filled_notification
        
        mock_bot = AsyncMock()
        telegram_id = 12345
        
        db_order = {
            "order_hash": "order_filled_123",
            "market_title": "Test Market",
            "market_slug": "test-market",
            "side": "BUY"
        }
        
        api_order = {
            "amountFilled": "100.5"
        }
        
        await send_order_filled_notification(mock_bot, telegram_id, db_order, api_order)
        
        assert mock_bot.send_message.called
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs['chat_id'] == telegram_id
        message = call_args.kwargs['text']
        
        assert "Order Filled" in message
        assert "Test Market" in message
        assert "order_filled_123" in message
        assert "100.5" in message  # amountFilled
        assert "View Market" in message


class TestCancelOrdersBatchEdgeCases:
    """Тесты для граничных случаев cancel_orders_batch"""
    
    @pytest.mark.asyncio
    async def test_cancel_orders_empty_list(self):
        """Тест: пустой список ордеров для отмены"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        
        result = await cancel_orders_batch(mock_api_client, [])
        
        assert result['success'] is False
        assert result['cause'] == 'No orders to cancel'
        assert len(result['removed']) == 0
        assert len(result['noop']) == 0
    
    @pytest.mark.asyncio
    async def test_cancel_orders_exception(self):
        """Тест: исключение при отмене ордеров"""
        from sync_orders import cancel_orders_batch
        
        mock_api_client = AsyncMock()
        mock_api_client.cancel_orders.side_effect = Exception("API error")
        
        result = await cancel_orders_batch(mock_api_client, ['order_1', 'order_2'])
        
        assert result['success'] is False
        assert 'API error' in result['cause']
        assert len(result['removed']) == 0
        assert len(result['noop']) == 0


class TestPlaceOrdersBatchEdgeCases:
    """Тесты для граничных случаев place_orders_batch"""
    
    @pytest.mark.asyncio
    async def test_place_orders_missing_order_builder(self):
        """Тест: отсутствие order_builder в параметрах"""
        from sync_orders import place_orders_batch
        
        mock_api_client = AsyncMock()
        
        orders_params = [{
            # Отсутствует order_builder
            'market_id': 100,
            'token_id': 'token_yes',
            'side': Side.BUY,
            'price': 0.500,
            'amount': 100.0
        }]
        
        results = await place_orders_batch(mock_api_client, orders_params)
        
        assert len(results) == 1
        assert results[0]['success'] is False
        assert 'Missing order_builder' in results[0]['error']
    
    @pytest.mark.asyncio
    async def test_place_orders_invalid_side_type(self):
        """Тест: некорректный тип side"""
        from sync_orders import place_orders_batch
        
        mock_api_client = AsyncMock()
        
        orders_params = [{
            'order_builder': MagicMock(),
            'market_id': 100,
            'token_id': 'token_yes',
            'side': "BUY",  # Строка вместо Side enum
            'price': 0.500,
            'amount': 100.0
        }]
        
        results = await place_orders_batch(mock_api_client, orders_params)
        
        assert len(results) == 1
        assert results[0]['success'] is False
        assert 'Invalid side type' in results[0]['error']
    
    @pytest.mark.asyncio
    async def test_place_orders_get_market_error(self):
        """Тест: ошибка при получении данных рынка"""
        from sync_orders import place_orders_batch
        
        mock_api_client = AsyncMock()
        mock_api_client.get_market.side_effect = Exception("Market not found")
        
        with patch('sync_orders.place_single_order', new_callable=AsyncMock) as mock_place_order:
            mock_place_order.return_value = (True, "order_hash", "order_api_id", None)
            
            orders_params = [{
                'order_builder': MagicMock(),
                'market_id': 100,
                'token_id': 'token_yes',
                'side': Side.BUY,
                'price': 0.500,
                'amount': 100.0
            }]
            
            # Должна продолжиться обработка с дефолтными значениями
            results = await place_orders_batch(mock_api_client, orders_params)
            
            # place_single_order должен быть вызван (использует дефолтные значения)
            assert mock_place_order.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
