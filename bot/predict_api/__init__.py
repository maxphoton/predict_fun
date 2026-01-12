"""
Predict.fun API клиент для работы с новым API.

Экспортирует основные классы и функции для работы с API.
"""

from .auth import (
    get_api_base_url,
    get_chain_id,
    get_jwt_token,
    get_rpc_url,
    refresh_jwt_token_if_needed,
)
from .client import PredictAPIClient
from .sdk_operations import (
    build_and_sign_limit_order,
    calculate_new_target_price,
    cancel_orders_via_sdk,
    get_usdt_balance,
    place_single_order,
    set_approvals,
)

__all__ = [
    "PredictAPIClient",
    "get_jwt_token",
    "refresh_jwt_token_if_needed",
    "get_rpc_url",
    "get_chain_id",
    "get_api_base_url",
    "get_usdt_balance",
    "cancel_orders_via_sdk",
    "build_and_sign_limit_order",
    "set_approvals",
    "place_single_order",
    "calculate_new_target_price",
]
