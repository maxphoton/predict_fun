"""
Predict.fun API клиент для работы с новым API.

Экспортирует основные классы и функции для работы с API.
"""
from .client import PredictAPIClient
from .auth import get_jwt_token, refresh_jwt_token_if_needed, get_rpc_url, get_chain_id, get_api_base_url
from .sdk_operations import (
    get_usdt_balance,
    cancel_orders_via_sdk,
    build_and_sign_limit_order,
    set_approvals,
    place_single_order,
    calculate_new_target_price
)

__all__ = [
    'PredictAPIClient',
    'get_jwt_token',
    'refresh_jwt_token_if_needed',
    'get_rpc_url',
    'get_chain_id',
    'get_api_base_url',
    'get_usdt_balance',
    'cancel_orders_via_sdk',
    'build_and_sign_limit_order',
    'set_approvals',
    'place_single_order',
    'calculate_new_target_price',
]

