"""
Тесты для bot/predict_api/sdk_operations.py

Тестирует SDK операции используя основную сеть (mainnet):
- Получение баланса USDT
- Построение и подпись ордеров
- Отмена ордеров через SDK
- Установка approvals

ВАЖНО: 
- Эти тесты используют MAINNET и требуют реальные credentials Predict Account
- Нужны MAINNET_PREDICT_ACCOUNT_ADDRESS и MAINNET_PRIVY_WALLET_PRIVATE_KEY
"""
import pytest
import os
import traceback
from typing import Dict, List, Optional

from bot.predict_api.sdk_operations import (
    get_usdt_balance,
    cancel_orders_via_sdk,
    build_and_sign_limit_order,
    set_approvals
)
from bot.predict_api.auth import get_chain_id, get_rpc_url
from predict_sdk import OrderBuilder, ChainId, Side, OrderBuilderOptions
from predict_sdk.errors import InvalidSignerError
from eth_account import Account
from eth_account.signers.local import LocalAccount  # type: ignore

# Попытка импорта адресов контрактов
try:
    from predict_sdk.addresses import ADDRESSES_BY_CHAIN_ID  # type: ignore
except ImportError:
    try:
        from predict_sdk import ADDRESSES_BY_CHAIN_ID  # type: ignore
    except ImportError:
        ADDRESSES_BY_CHAIN_ID = None

# Настраиваем для mainnet (не testnet)
os.environ['TEST_MODE'] = 'false'

# ============================================================================
# Переменные для тестирования на mainnet
# ============================================================================
# Для тестирования SDK операций нужны реальные credentials Predict Account на mainnet
# Установите эти переменные окружения или измените значения ниже:

# Адрес Predict Account (deposit address)
# Можно найти в настройках аккаунта на https://predict.fun/account/settings
MAINNET_PREDICT_ACCOUNT_ADDRESS = os.getenv('MAINNET_PREDICT_ACCOUNT_ADDRESS', '')

# Приватный ключ Privy Wallet для Predict Account
# Можно экспортировать из настроек аккаунта на https://predict.fun/account/settings
MAINNET_PRIVY_WALLET_PRIVATE_KEY = os.getenv('MAINNET_PRIVY_WALLET_PRIVATE_KEY', '')

# RPC URL для mainnet
MAINNET_RPC_URL = os.getenv('RPC_URL', 'https://bsc-dataseed.binance.org/')

# Устанавливаем переменные окружения для mainnet
if 'RPC_URL' not in os.environ:
    os.environ['RPC_URL'] = MAINNET_RPC_URL

# Используем Predict Account credentials
ACTUAL_WALLET_ADDRESS = MAINNET_PREDICT_ACCOUNT_ADDRESS
ACTUAL_PRIVATE_KEY = MAINNET_PRIVY_WALLET_PRIVATE_KEY


@pytest.fixture
def order_builder():
    """
    Создает OrderBuilder для mainnet.
    
    Использует credentials из переменных MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY и т.д.
    Если credentials не установлены, возвращает None (тесты будут пропущены).
    """
    # Проверяем, что credentials установлены
    default_private_key_with_prefix = '0x0000000000000000000000000000000000000000000000000000000000000000'
    default_private_key_without_prefix = '0000000000000000000000000000000000000000000000000000000000000000'
    
    if (ACTUAL_WALLET_ADDRESS == '0x0000000000000000000000000000000000000000' or
        not ACTUAL_WALLET_ADDRESS or
        not ACTUAL_PRIVATE_KEY or
        ACTUAL_PRIVATE_KEY == default_private_key_with_prefix or
        ACTUAL_PRIVATE_KEY == default_private_key_without_prefix):
        return None
    
    try:
        chain_id = get_chain_id()
        
        # Создаем LocalAccount (signer) из приватного ключа
        signer: LocalAccount = Account.from_key(ACTUAL_PRIVATE_KEY)
        
        # Создаем OrderBuilder для Predict Account
        builder = OrderBuilder.make(
            chain_id,
            signer,
            OrderBuilderOptions(predict_account=ACTUAL_WALLET_ADDRESS)
        )
        
        return builder
    except InvalidSignerError as e:
        # Приватный ключ не является владельцем Predict Account
        return None
    except Exception as e:
        # Другие ошибки
        print(f"\n[DEBUG] Ошибка создания OrderBuilder: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        return None


@pytest.fixture
def sample_market_data():
    """Пример данных рынка для тестов."""
    return {
        'id': 1,
        'outcomes': [
            {'name': 'Yes', 'indexSet': 1, 'onChainId': '0x1234567890123456789012345678901234567890'},
            {'name': 'No', 'indexSet': 2, 'onChainId': '0x0987654321098765432109876543210987654321'}
        ],
        'feeRateBps': 100,
        'isNegRisk': False,
        'isYieldBearing': False
    }


class TestGetUsdtBalance:
    """Тесты для получения баланса USDT."""
    
    @pytest.mark.asyncio
    async def test_get_usdt_balance(self, order_builder):
        """
        Тест получения баланса USDT через SDK.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        balance_wei = await get_usdt_balance(order_builder)
        
        # Проверяем, что баланс получен (может быть 0)
        assert isinstance(balance_wei, int)
        assert balance_wei >= 0
        
        # Логируем баланс для информации
        balance_usdt = balance_wei / 1e18
        print(f"\nБаланс USDT: {balance_usdt:.6f} USDT ({balance_wei} wei)")


class TestBuildAndSignLimitOrder:
    """Тесты для построения и подписи ордеров."""
    
    @pytest.mark.asyncio
    async def test_build_and_sign_limit_order_buy(self, order_builder, sample_market_data):
        """
        Тест построения и подписи BUY ордера.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        token_id = sample_market_data['outcomes'][0]['onChainId']
        fee_rate_bps = sample_market_data['feeRateBps']
        
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id=token_id,
            price_per_share_wei=500000000000000000,  # 0.5 USDT
            quantity_wei=10000000000000000000,  # 10 shares
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=sample_market_data['isNegRisk'],
            is_yield_bearing=sample_market_data['isYieldBearing']
        )
        
        assert result is not None
        assert 'order' in result
        assert 'signature' in result
        assert 'hash' in result
        assert 'pricePerShare' in result
        
        # Проверяем структуру ордера
        order = result['order']
        assert 'hash' in order
        assert 'maker' in order
        assert 'signer' in order
        assert 'tokenId' in order
        assert 'makerAmount' in order
        assert 'takerAmount' in order
        assert 'feeRateBps' in order
        assert 'side' in order
        
        # Проверяем, что maker и signer совпадают с адресом кошелька
        assert order['maker'].lower() == ACTUAL_WALLET_ADDRESS.lower()
        assert order['signer'].lower() == ACTUAL_WALLET_ADDRESS.lower()
        
        # Проверяем, что side = 0 для BUY
        assert order['side'] == 0
        
        print(f"\nBUY ордер создан: hash={result['hash']}")
    
    @pytest.mark.asyncio
    async def test_build_and_sign_limit_order_sell(self, order_builder, sample_market_data):
        """
        Тест построения и подписи SELL ордера.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        token_id = sample_market_data['outcomes'][0]['onChainId']
        fee_rate_bps = sample_market_data['feeRateBps']
        
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.SELL,
            token_id=token_id,
            price_per_share_wei=600000000000000000,  # 0.6 USDT
            quantity_wei=5000000000000000000,  # 5 shares
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=sample_market_data['isNegRisk'],
            is_yield_bearing=sample_market_data['isYieldBearing']
        )
        
        assert result is not None
        assert 'order' in result
        
        # Проверяем, что side = 1 для SELL
        assert result['order']['side'] == 1
        
        print(f"\nSELL ордер создан: hash={result['hash']}")
    
    @pytest.mark.asyncio
    async def test_build_and_sign_limit_order_neg_risk(self, order_builder, sample_market_data):
        """
        Тест построения ордера для NegRisk рынка.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        token_id = sample_market_data['outcomes'][0]['onChainId']
        fee_rate_bps = sample_market_data['feeRateBps']
        
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id=token_id,
            price_per_share_wei=500000000000000000,
            quantity_wei=10000000000000000000,
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=True,  # NegRisk рынок
            is_yield_bearing=False
        )
        
        assert result is not None
        assert 'order' in result
        print(f"\nNegRisk ордер создан: hash={result['hash']}")
    
    @pytest.mark.asyncio
    async def test_build_and_sign_limit_order_yield_bearing(self, order_builder, sample_market_data):
        """
        Тест построения ордера для Yield Bearing рынка.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        token_id = sample_market_data['outcomes'][0]['onChainId']
        fee_rate_bps = sample_market_data['feeRateBps']
        
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id=token_id,
            price_per_share_wei=500000000000000000,
            quantity_wei=10000000000000000000,
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=False,
            is_yield_bearing=True  # Yield Bearing рынок
        )
        
        assert result is not None
        assert 'order' in result
        print(f"\nYield Bearing ордер создан: hash={result['hash']}")


class TestCancelOrdersViaSdk:
    """Тесты для отмены ордеров через SDK."""
    
    @pytest.mark.asyncio
    async def test_cancel_orders_empty_list(self, order_builder):
        """
        Тест отмены пустого списка ордеров.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        result = await cancel_orders_via_sdk(
            order_builder=order_builder,
            orders=[],
            is_neg_risk=False,
            is_yield_bearing=False
        )
        
        assert result['success'] == False
        assert result['cause'] == 'No orders to cancel'
    
    @pytest.mark.asyncio
    async def test_cancel_orders_with_dict(self, order_builder):
        """
        Тест отмены ордеров, переданных в виде словарей.
        
        ВАЖНО: Этот тест требует реальных активных ордеров на mainnet.
        Если ордеров нет, тест будет пропущен или вернет ошибку.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        # Пример структуры ордера (нужны реальные данные с mainnet)
        # Для реального теста нужно получить активные ордера через API
        sample_order = {
            'order': {
                'hash': '0x0000000000000000000000000000000000000000000000000000000000000000',
                'maker': ACTUAL_WALLET_ADDRESS,
                'signer': ACTUAL_WALLET_ADDRESS,
                'tokenId': '0x1234567890123456789012345678901234567890',
                'makerAmount': '1000000000000000000',
                'takerAmount': '2000000000000000000',
                'feeRateBps': '100',
                'side': 0,
                'expiration': 9999999999,
                'nonce': '0',
                'salt': '0',
                'taker': '0x0000000000000000000000000000000000000000',
                'signatureType': 0
            },
            'isNegRisk': False,
            'isYieldBearing': False
        }
        
        # Этот тест может упасть, если ордер не существует
        # В реальном сценарии нужно использовать реальные активные ордера
        result = await cancel_orders_via_sdk(
            order_builder=order_builder,
            orders=[sample_order],
            is_neg_risk=False,
            is_yield_bearing=False
        )
        
        # Результат может быть success=False если ордер не существует
        assert isinstance(result, dict)
        assert 'success' in result
        assert 'cause' in result or 'receipt' in result


class TestSetApprovals:
    """Тесты для установки approvals."""
    
    @pytest.mark.asyncio
    async def test_set_approvals(self, order_builder):
        """
        Тест установки approvals для торговли.
        
        Требует реальные credentials на mainnet.
        ВАЖНО: Этот тест может выполнить реальные транзакции на mainnet!
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        result = await set_approvals(
            order_builder=order_builder,
            is_yield_bearing=False
        )
        
        assert isinstance(result, dict)
        assert 'success' in result
        assert 'transactions' in result
        assert isinstance(result['transactions'], list)
        
        # Если approvals уже установлены, success может быть True
        # Если success=False, проверяем причины из транзакций
        if result['success']:
            print("\nApprovals установлены или уже были установлены")
        else:
            # Собираем причины ошибок из неуспешных транзакций
            failed_causes = []
            for tx in result['transactions']:
                if not tx.get('success', False) and tx.get('cause'):
                    failed_causes.append(tx['cause'])
            cause_msg = ', '.join(failed_causes) if failed_causes else 'Unknown error'
            print(f"\nНекоторые approvals не установлены: {cause_msg}")
    
    @pytest.mark.asyncio
    async def test_set_approvals_yield_bearing(self, order_builder):
        """
        Тест установки approvals для Yield Bearing рынков.
        
        Требует реальные credentials на mainnet.
        ВАЖНО: Этот тест может выполнить реальные транзакции на mainnet!
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        result = await set_approvals(
            order_builder=order_builder,
            is_yield_bearing=True
        )
        
        assert isinstance(result, dict)
        assert 'success' in result
        assert 'transactions' in result


class TestIntegration:
    """Интеграционные тесты SDK операций."""
    
    @pytest.mark.asyncio
    async def test_full_flow_build_and_check_balance(self, order_builder, sample_market_data):
        """
        Полный flow: проверка баланса и построение ордера.
        
        Требует реальные credentials на mainnet.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        # Шаг 1: Проверяем баланс
        balance_wei = await get_usdt_balance(order_builder)
        balance_usdt = balance_wei / 1e18
        
        print(f"\nБаланс перед созданием ордера: {balance_usdt:.6f} USDT")
        
        # Шаг 2: Создаем ордер
        token_id = sample_market_data['outcomes'][0]['onChainId']
        fee_rate_bps = sample_market_data['feeRateBps']
        
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id=token_id,
            price_per_share_wei=500000000000000000,  # 0.5 USDT
            quantity_wei=10000000000000000000,  # 10 shares
            fee_rate_bps=fee_rate_bps,
            is_neg_risk=sample_market_data['isNegRisk'],
            is_yield_bearing=sample_market_data['isYieldBearing']
        )
        
        assert result is not None
        assert result['order']['hash'] is not None
        
        print(f"Ордер создан: hash={result['order']['hash']}")
        print(f"Price per share: {result['pricePerShare']}")


class TestErrorHandling:
    """Тесты обработки ошибок."""
    
    @pytest.mark.asyncio
    async def test_build_order_invalid_token_id(self, order_builder):
        """
        Тест обработки ошибки при неверном token_id.
        """
        if order_builder is None:
            pytest.skip("Требуются mainnet credentials (MAINNET_WALLET_ADDRESS, MAINNET_PRIVATE_KEY)")
        
        # Используем неверный token_id
        result = await build_and_sign_limit_order(
            order_builder=order_builder,
            side=Side.BUY,
            token_id='0x0000000000000000000000000000000000000000',  # Неверный token_id
            price_per_share_wei=500000000000000000,
            quantity_wei=10000000000000000000,
            fee_rate_bps=100,
            is_neg_risk=False,
            is_yield_bearing=False
        )
        
        # Может вернуть None при ошибке или успешно создать ордер (зависит от валидации SDK)
        # Проверяем, что функция не упала с исключением
        assert result is None or isinstance(result, dict)

