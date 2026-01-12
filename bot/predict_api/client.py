"""
REST API клиент для Predict.fun.

Реализует все методы для работы с новым API Predict.fun.
Управляет JWT токеном и автоматически обновляет его при необходимости.
"""
import asyncio
import logging
from typing import Dict, List, Optional

import requests

from .auth import get_api_base_url, refresh_jwt_token_if_needed

logger = logging.getLogger(__name__)


class PredictAPIClient:
    """
    Клиент для работы с Predict.fun API.
    
    Управляет аутентификацией (JWT токен) и предоставляет методы для работы с API.
    Автоматически обновляет JWT токен при получении ошибки 401.
    """
    
    def __init__(
        self,
        api_key: str,
        wallet_address: str,
        private_key: str
    ):
        """
        Инициализирует API клиент.
        
        Args:
            api_key: API ключ Predict.fun
            wallet_address: Deposit Address (адрес Predict Account)
            private_key: Приватный ключ Privy Wallet
        """
        self.api_key = api_key
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.jwt_token: Optional[str] = None
        
        # Внутренняя сессия для управления токеном
        self._session = {
            'api_key': api_key,
            'wallet_address': wallet_address,
            'private_key': private_key,
            'jwt_token': None
        }
    
    async def _get_headers(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Получить заголовки для API запросов с актуальным JWT токеном.
        
        Args:
            force_refresh: Принудительно обновить токен
        
        Returns:
            Словарь с заголовками
        """
        # Обновляем токен если нужно
        await refresh_jwt_token_if_needed(self._session, force_refresh=force_refresh)
        self.jwt_token = self._session.get('jwt_token')
        
        if not self.jwt_token:
            raise ValueError("JWT токен не получен. Проверьте аутентификацию.")
        
        return {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'Authorization': f'Bearer {self.jwt_token}'
        }
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry_on_401: bool = True,
        require_jwt: bool = True
    ) -> Optional[Dict]:
        """
        Выполнить HTTP запрос к API.
        
        Args:
            method: HTTP метод (GET, POST, DELETE и т.д.)
            endpoint: Endpoint API (без базового URL)
            params: Query параметры
            json_data: JSON тело запроса
            retry_on_401: Повторить запрос после обновления токена при 401
            require_jwt: Требуется ли JWT токен (False для публичных endpoints, только api-key)
        
        Returns:
            JSON ответ или None в случае ошибки
        """
        api_base_url = get_api_base_url()
        url = f"{api_base_url}/{endpoint.lstrip('/')}"
        
        try:
            # Формируем заголовки
            if require_jwt:
                headers = await self._get_headers()
            else:
                # Для публичных endpoints нужен только api-key
                headers = {
                    'Content-Type': 'application/json',
                    'x-api-key': self.api_key
                }
            
            # Выполняем запрос в отдельном потоке
            def _make_request_sync():
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=30
                )
                return response
            
            response = await asyncio.to_thread(_make_request_sync)
            
            # Если получили 401, пробуем обновить токен и повторить запрос (только если требуется JWT)
            if response.status_code == 401 and retry_on_401 and require_jwt:
                logger.warning("Получен 401, обновляем JWT токен и повторяем запрос")
                headers = await self._get_headers(force_refresh=True)
                
                def _retry_request_sync():
                    return requests.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        json=json_data,
                        timeout=30
                    )
                
                response = await asyncio.to_thread(_retry_request_sync)
            
            # Парсим JSON ответ (всегда, независимо от статус-кода)
            try:
                data = response.json()
                # Если статус не успешный, логируем ошибку, но возвращаем данные
                if response.status_code not in (200, 201):
                    logger.error(
                        f"Ошибка API запроса {method} {url}: "
                        f"status={response.status_code}, response={response.text}"
                    )
                return data
            except ValueError as e:
                # Если не JSON, логируем и возвращаем None
                logger.error(
                    f"Ошибка парсинга JSON ответа {method} {url}: {e}. "
                    f"Status={response.status_code}, response={response.text}"
                )
                return None
                
        except Exception as e:
            logger.error(f"Исключение при выполнении API запроса {method} {endpoint}: {e}")
            return None
    
    # ============================================================================
    # Методы для работы с рынками
    # ============================================================================
    
    async def get_market(self, market_id: int) -> Optional[Dict]:
        """
        Получить информацию о рынке.
        
        Согласно документации: https://dev.predict.fun/get-market-by-id-25552989e0
        
        Args:
            market_id: ID рынка (будет преобразован в string для path параметра)
        
        Returns:
            Словарь с данными рынка или None в случае ошибки.
            Структура ответа: {
                'id': int,
                'title': str,
                'question': str,
                'description': str,
                'status': str,  # REGISTERED, PRICE_PROPOSED, PRICE_DISPUTED, PAUSED, UNPAUSED, RESOLVED
                'isNegRisk': bool,
                'isYieldBearing': bool,
                'feeRateBps': int,
                'outcomes': [{'name': str, 'indexSet': int, 'onChainId': str, 'status': str}],
                'conditionId': str,
                ...
            }
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        data = await self._make_request('GET', f'markets/{market_id}', require_jwt=False)
        if data and 'data' in data:
            return data['data']
        return None
    
    async def get_orderbook(self, market_id: int) -> Optional[Dict]:
        """
        Получить orderbook для рынка.
        
        Согласно документации: https://dev.predict.fun/get-the-orderbook-for-a-market-25326908e0
        
        Args:
            market_id: ID рынка
        
        Returns:
            Словарь с orderbook или None в случае ошибки.
            Структура ответа: {
                'marketId': int,
                'updateTimestampMs': int,
                'asks': [[price, size], ...],  # Массив массивов [цена, размер]
                'bids': [[price, size], ...]   # Массив массивов [цена, размер]
            }
        
        Note:
            - Orderbook хранит цены на основе исхода "Yes"
            - Для расчета цены "No": price_no = 1 - price_yes
            - Требует только x-api-key (не требует JWT для чтения)
        """
        data = await self._make_request('GET', f'markets/{market_id}/orderbook', require_jwt=False)
        if data and 'data' in data:
            return data['data']
        return None
    
    # ============================================================================
    # Методы для работы с ордерами
    # ============================================================================
    
    async def get_my_orders(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None,
        status: Optional[str] = None
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Получить ордера пользователя.
        
        Согласно документации: https://dev.predict.fun/get-orders-25326902e0
        
        Args:
            first: Количество ордеров для получения (string, число). Если None, используется значение по умолчанию API.
            after: Cursor для пагинации (string). Если None, возвращаются первые ордера.
            status: Фильтр по статусу. Возможные значения: 'OPEN', 'FILLED'. Если None, возвращаются все статусы.
        
        Returns:
            Tuple: (список ордеров, cursor для следующей страницы или None)
            Структура каждого ордера: {
                'order': {
                    'hash': str,
                    'salt': str,
                    'maker': str,
                    'signer': str,
                    'taker': str,
                    'tokenId': str,
                    'makerAmount': str,
                    'takerAmount': str,
                    'expiration': str|int,
                    'nonce': str,
                    'feeRateBps': str,
                    'side': 0|1,  # 0=BUY, 1=SELL
                    'signatureType': 0,
                    'signature': str
                },
                'id': str,
                'marketId': int,
                'currency': str,
                'amount': str,
                'amountFilled': str,
                'isNegRisk': bool,
                'isYieldBearing': bool,
                'strategy': 'LIMIT'|'MARKET',
                'status': 'OPEN'|'FILLED'|'EXPIRED'|'CANCELLED'|'INVALIDATED',
                'rewardEarningRate': float
            }
        
        Note:
            Требует x-api-key и JWT токен (Bearer Authentication).
        """
        params = {}
        if first is not None:
            params['first'] = str(first)  # API ожидает string
        if after:
            params['after'] = after
        if status:
            # Валидация статуса
            if status.upper() not in ('OPEN', 'FILLED'):
                logger.warning(f"Некорректный статус {status}, допустимые: OPEN, FILLED")
            else:
                params['status'] = status.upper()
        
        data = await self._make_request('GET', 'orders', params=params)
        if data and 'data' in data:
            orders = data['data']
            cursor = data.get('cursor')  # Может быть None
            if isinstance(orders, list):
                return orders, cursor
        return [], None
    
    async def get_order_by_id(self, order_hash: str) -> Optional[Dict]:
        """
        Получить ордер по hash.
        
        Согласно документации: https://dev.predict.fun/get-order-by-hash-25326901e0
        
        Args:
            order_hash: Hash ордера (order.hash из структуры ордера)
        
        Returns:
            Словарь с данными ордера или None в случае ошибки.
            Структура такая же как в get_my_orders().
        
        Note:
            Требует x-api-key и JWT токен (Bearer Authentication).
        """
        data = await self._make_request('GET', f'orders/{order_hash}')
        if data and 'data' in data:
            return data['data']
        return None
    
    async def place_order(
        self,
        order: Dict,
        price_per_share: str,
        strategy: str = "LIMIT",
        slippage_bps: Optional[str] = None,
        is_fill_or_kill: bool = False
    ) -> Optional[Dict]:
        """
        Разместить ордер.
        
        Согласно OpenAPI спецификации: POST /v1/orders
        
        Args:
            order: Словарь с данными подписанного ордера (из OrderBuilder).
                Должен содержать: hash, salt, maker, signer, taker, tokenId,
                makerAmount, takerAmount, expiration, nonce, feeRateBps, side,
                signatureType, signature
            price_per_share: Цена за акцию в wei (обязательный параметр, integer string)
            strategy: Стратегия ордера ('LIMIT' или 'MARKET', по умолчанию 'LIMIT')
            slippage_bps: Допустимое проскальзывание в базисных пунктах (опционально, для MARKET)
            is_fill_or_kill: Fill or kill флаг (опционально, только для MARKET, по умолчанию False)
        
        Returns:
            Словарь с данными созданного ордера или None в случае ошибки.
            Структура ответа: {
                'code': 'OK',
                'orderId': str,  # bigint string
                'orderHash': str
            }
        
        Note:
            Требует x-api-key и JWT токен (Bearer Authentication).
        """
        # Проверяем, что order содержит все обязательные поля
        required_order_fields = ['salt', 'maker', 'signer', 'taker', 'tokenId', 'makerAmount', 
                                'takerAmount', 'expiration', 'nonce', 'feeRateBps', 'side', 
                                'signatureType', 'signature']
        missing_fields = [field for field in required_order_fields if field not in order or order[field] is None]
        if missing_fields:
            logger.error(f"Отсутствуют обязательные поля в order: {missing_fields}")
            return None
        
        request_data = {
            'data': {
                'pricePerShare': price_per_share,  # Обязательный параметр, integer string
                'strategy': strategy.upper(),
                'order': order
            }
        }
        
        # Согласно документации, slippageBps обязателен (non-empty string)
        # Для LIMIT можно передать "0", для MARKET должен быть указан
        if slippage_bps is not None:
            request_data['data']['slippageBps'] = str(slippage_bps)
        else:
            # Если не указан, используем "0" (для LIMIT это нормально)
            request_data['data']['slippageBps'] = "0"
        
        # Логируем запрос для отладки (без signature для безопасности)
        order_for_log = {k: v for k, v in order.items() if k != 'signature'}
        logger.debug(f"Place order request: pricePerShare={price_per_share}, strategy={strategy.upper()}, order keys={list(order_for_log.keys())}")
        
        if is_fill_or_kill:
            request_data['data']['isFillOrKill'] = is_fill_or_kill
        
        data = await self._make_request('POST', 'orders', json_data=request_data)
        if data and 'data' in data:
            return data['data']
        # Если data есть, но нет 'data', значит это ошибка - возвращаем её для обработки
        if data:
            return data
        return None
    
    async def cancel_orders(self, order_ids: List[str]) -> Dict:
        """
        Удалить ордера из orderbook (НЕ on-chain отмена).
        
        Согласно OpenAPI спецификации: POST /v1/orders/remove
        
        Args:
            order_ids: Список ID ордеров для удаления (1-100 элементов).
                       Каждый ID - это строка, которая декодируется в bigint.
        
        Returns:
            Словарь с результатом операции: {
                'success': bool,
                'removed': List[str],  # ID ордеров, которые были успешно удалены
                'noop': List[str]      # ID ордеров, которые уже были удалены/исполнены/отменены
            }
        
        Note:
            - Требует x-api-key и JWT токен (Bearer Authentication)
            - Это только удаление из orderbook, НЕ on-chain отмена
            - Для полной отмены используйте cancel_orders_via_sdk() из sdk_operations для on-chain отмены
            - Максимум 100 ордеров за один запрос
        """
        if not order_ids:
            return {'success': False, 'removed': [], 'noop': []}
        
        if len(order_ids) > 100:
            logger.warning(f"Слишком много ордеров ({len(order_ids)}), максимум 100. Берем первые 100.")
            order_ids = order_ids[:100]
        
        # Согласно OpenAPI спецификации, структура запроса:
        request_data = {
            'data': {
                'ids': order_ids
            }
        }
        
        data = await self._make_request('POST', 'orders/remove', json_data=request_data)
        if data:
            return data
        return {'success': False, 'removed': [], 'noop': []}
    
    # ============================================================================
    # Методы для работы с балансами и позициями
    # ============================================================================
    
    async def get_positions(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Получить позиции пользователя.
        
        Согласно OpenAPI спецификации: GET /v1/positions
        
        Args:
            first: Количество позиций для получения (string, число). Если None, используется значение по умолчанию API.
            after: Cursor для пагинации (string). Если None, возвращаются первые позиции.
        
        Returns:
            Tuple: (список позиций, cursor для следующей страницы или None)
            Структура каждой позиции: {
                'id': str,
                'market': Dict,  # Информация о рынке
                'outcome': Dict,  # Информация об исходе
                'amount': str,    # bigint string
                'valueUsd': str   # string
            }
        
        Note:
            Требует x-api-key и JWT токен (Bearer Authentication).
        """
        params = {}
        if first is not None:
            params['first'] = str(first)
        if after:
            params['after'] = after
        
        data = await self._make_request('GET', 'positions', params=params)
        if data and 'data' in data:
            positions = data['data']
            cursor = data.get('cursor')
            if isinstance(positions, list):
                return positions, cursor
        return [], None
    
    # ============================================================================
    # Методы для работы с аккаунтом
    # ============================================================================
    
    async def get_account(self) -> Optional[Dict]:
        """
        Получить информацию об аккаунте пользователя.
        
        Согласно OpenAPI спецификации: GET /v1/account
        
        Returns:
            Словарь с данными аккаунта или None в случае ошибки.
            Структура ответа: {
                'name': str,
                'address': str,
                'imageUrl': Optional[str],
                'referral': {
                    'code': Optional[str],  # 5 символов или None
                    'status': 'LOCKED' | 'UNLOCKED'
                }
            }
        
        Note:
            Требует x-api-key и JWT токен (Bearer Authentication).
        """
        data = await self._make_request('GET', 'account')
        if data and 'data' in data:
            return data['data']
        return None
    
    async def set_referral(self, referral_code: str) -> bool:
        """
        Установить реферальный код (если еще не установлен).
        
        Согласно OpenAPI спецификации: POST /v1/account/referral
        
        Args:
            referral_code: Реферальный код (должен быть 5 символов)
        
        Returns:
            True если код успешно установлен, False в случае ошибки
        
        Note:
            - Требует x-api-key и JWT токен (Bearer Authentication)
            - Код можно установить только один раз
            - Если код уже установлен, вернется ошибка
        """
        if len(referral_code) != 5:
            logger.error(f"Реферальный код должен быть 5 символов, получено: {len(referral_code)}")
            return False
        
        request_data = {
            'data': {
                'referralCode': referral_code
            }
        }
        
        data = await self._make_request('POST', 'account/referral', json_data=request_data)
        return data is not None and data.get('success', False)
    
    # ============================================================================
    # Методы для работы с рынками (дополнительные)
    # ============================================================================
    
    async def get_markets(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Получить список рынков.
        
        Согласно OpenAPI спецификации: GET /v1/markets
        
        Args:
            first: Количество рынков для получения (string, число). Если None, используется значение по умолчанию API.
            after: Cursor для пагинации (string). Если None, возвращаются первые рынки.
        
        Returns:
            Tuple: (список рынков, cursor для следующей страницы или None)
            Структура каждого рынка: {
                'id': int,
                'imageUrl': str,
                'title': str,
                'question': str,
                'description': str,
                'status': str,  # REGISTERED, PRICE_PROPOSED, PRICE_DISPUTED, PAUSED, UNPAUSED, RESOLVED
                'isNegRisk': bool,
                'isYieldBearing': bool,
                'feeRateBps': int,
                'resolution': Optional[Dict],
                'outcomes': List[Dict],
                'conditionId': str,
                ...
            }
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        params = {}
        if first is not None:
            params['first'] = str(first)
        if after:
            params['after'] = after
        
        data = await self._make_request('GET', 'markets', params=params, require_jwt=False)
        if data and 'data' in data:
            markets = data['data']
            cursor = data.get('cursor')
            if isinstance(markets, list):
                return markets, cursor
        return [], None
    
    async def get_market_stats(self, market_id: int) -> Optional[Dict]:
        """
        Получить статистику рынка.
        
        Согласно OpenAPI спецификации: GET /v1/markets/{id}/stats
        
        Args:
            market_id: ID рынка
        
        Returns:
            Словарь со статистикой или None в случае ошибки.
            Структура ответа: {
                'totalLiquidityUsd': float,
                'volumeTotalUsd': float,
                'volume24hUsd': float
            }
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        data = await self._make_request('GET', f'markets/{market_id}/stats', require_jwt=False)
        if data and 'data' in data:
            return data['data']
        return None
    
    async def get_market_last_sale(self, market_id: int) -> Optional[Dict]:
        """
        Получить информацию о последней продаже на рынке.
        
        Согласно OpenAPI спецификации: GET /v1/markets/{id}/last-sale
        
        Args:
            market_id: ID рынка
        
        Returns:
            Словарь с информацией о последней продаже или None в случае ошибки/отсутствия продаж.
            Структура ответа: {
                'quoteType': 'Ask' | 'Bid',
                'outcome': 'Yes' | 'No',
                'priceInCurrency': str,
                'strategy': 'MARKET' | 'LIMIT'
            } или None если продаж еще не было
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        data = await self._make_request('GET', f'markets/{market_id}/last-sale', require_jwt=False)
        if data and 'data' in data:
            return data['data']  # Может быть None если продаж еще не было
        return None
    
    # ============================================================================
    # Методы для работы с совпадениями ордеров
    # ============================================================================
    
    async def get_order_matches(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None,
        category_id: Optional[str] = None,
        market_id: Optional[int] = None,
        min_value_usdt_wei: Optional[str] = None,
        signer_address: Optional[str] = None,
        is_signer_maker: Optional[bool] = None
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Получить список событий совпадения ордеров (matches).
        
        Согласно OpenAPI спецификации: GET /v1/orders/matches
        
        Args:
            first: Количество событий для получения (string, число)
            after: Cursor для пагинации (string)
            category_id: Фильтр по ID категории (string)
            market_id: Фильтр по ID рынка (int)
            min_value_usdt_wei: Минимальное значение в USDT wei (string)
            signer_address: Адрес подписанта для фильтрации (string)
            is_signer_maker: Фильтр по роли подписанта:
                - True: подписант является maker
                - False: подписант является taker
                - None: без фильтра
        
        Returns:
            Tuple: (список событий совпадения, cursor для следующей страницы или None)
            Структура каждого события: {
                'market': Dict,  # Информация о рынке
                'taker': Dict,   # Информация о taker
                'amountFilled': str,
                'priceExecuted': str,
                'makers': List[Dict],  # Список makers
                'transactionHash': str,
                'executedAt': str  # date string
            }
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        params = {}
        if first is not None:
            params['first'] = str(first)
        if after:
            params['after'] = after
        if category_id:
            params['categoryId'] = category_id
        if market_id is not None:
            params['marketId'] = str(market_id)
        if min_value_usdt_wei:
            params['minValueUsdtWei'] = min_value_usdt_wei
        if signer_address:
            params['signerAddress'] = signer_address
        if is_signer_maker is not None:
            params['isSignerMaker'] = 'true' if is_signer_maker else 'false'
        
        data = await self._make_request('GET', 'orders/matches', params=params, require_jwt=False)
        if data and 'data' in data:
            matches = data['data']
            cursor = data.get('cursor')
            if isinstance(matches, list):
                return matches, cursor
        return [], None
    
    # ============================================================================
    # Методы для работы с категориями
    # ============================================================================
    
    async def get_categories(
        self,
        first: Optional[int] = None,
        after: Optional[str] = None,
        status: Optional[str] = None,
        sort: Optional[str] = None
    ) -> tuple[List[Dict], Optional[str]]:
        """
        Получить список категорий и их рынков.
        
        Согласно OpenAPI спецификации: GET /v1/categories
        
        Args:
            first: Количество категорий для получения (string, число)
            after: Cursor для пагинации (string)
            status: Фильтр по статусу ('OPEN' или 'RESOLVED')
            sort: Сортировка:
                - 'VOLUME_24H_DESC': По объему за 24 часа (убывание)
                - 'VOLUME_ALL_DESC': По общему объему (убывание)
                - 'PUBLISHED_AT_ASC': По дате публикации (возрастание)
                - 'PUBLISHED_AT_DESC': По дате публикации (убывание, по умолчанию)
        
        Returns:
            Tuple: (список категорий, cursor для следующей страницы или None)
            Структура каждой категории: {
                'id': int,
                'slug': str,
                'title': str,
                'description': str,
                'imageUrl': str,
                'isNegRisk': bool,
                'isYieldBearing': bool,
                'marketVariant': str,  # DEFAULT, SPORTS_MATCH, CRYPTO_UP_DOWN, TWEET_COUNT
                'createdAt': str,  # date string
                'publishedAt': str,  # date string
                'markets': List[Dict],  # Список рынков в категории
                'startsAt': str,  # date string
                'endsAt': Optional[str],  # date string
                'status': str,  # OPEN, RESOLVED
                'tags': List[Dict]
            }
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        params = {}
        if first is not None:
            params['first'] = str(first)
        if after:
            params['after'] = after
        if status:
            if status.upper() in ('OPEN', 'RESOLVED'):
                params['status'] = status.upper()
        if sort:
            valid_sorts = ('VOLUME_24H_DESC', 'VOLUME_ALL_DESC', 'PUBLISHED_AT_ASC', 'PUBLISHED_AT_DESC')
            if sort.upper() in valid_sorts:
                params['sort'] = sort.upper()
        
        data = await self._make_request('GET', 'categories', params=params, require_jwt=False)
        if data and 'data' in data:
            categories = data['data']
            cursor = data.get('cursor')
            if isinstance(categories, list):
                return categories, cursor
        return [], None
    
    async def get_category(self, slug: str) -> Optional[Dict]:
        """
        Получить информацию о категории по slug.
        
        Согласно OpenAPI спецификации: GET /v1/categories/{slug}
        
        Args:
            slug: Slug категории (string)
        
        Returns:
            Словарь с данными категории или None в случае ошибки.
            Структура такая же как в get_categories().
        
        Note:
            Требует только x-api-key (не требует JWT для чтения).
        """
        data = await self._make_request('GET', f'categories/{slug}', require_jwt=False)
        if data and 'data' in data:
            return data['data']
        return None
    

