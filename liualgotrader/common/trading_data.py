"""Global trading state shared within a process."""

from asyncio import Queue
from typing import Dict, List, Optional, Tuple

import pandas as pd

from liualgotrader.common.types import Order
from liualgotrader.db.models.ticker_snapshot import TickerSnapshot
from liualgotrader.strategy.base import Strategy

strategies: List[Strategy] = []
open_orders: Dict[str, Order] = {}
open_order_strategy: Dict[str, Strategy] = {}
last_used_strategy: Dict[str, Strategy] = {}
latest_cost_basis: Dict[str, float] = {}
latest_scalp_basis: Dict[str, float] = {}
sell_indicators: Dict[str, Dict] = {}
buy_indicators: Dict[str, Dict] = {}
positions: Dict[str, float] = {}
target_prices: Dict[str, float] = {}
stop_prices: Dict[str, float] = {}
partial_fills: Dict[str, float] = {}
partial_fills_fee: Dict[str, float] = {}
symbol_resistance: Dict[str, float] = {}
voi: Dict[str, List[float]] = {}
voi_ask: Dict[str, Tuple[float, float, pd.Timestamp]] = {}
voi_bid: Dict[str, Tuple[float, float, pd.Timestamp]] = {}


snapshot: Dict[str, TickerSnapshot] = {}

cool_down: Dict[str, Optional[pd.Timestamp]] = {}

queues: Dict[str, Queue] = {}
down_cross: Dict[str, pd.Timestamp] = {}

buy_time: Dict[str, pd.Timestamp] = {}
