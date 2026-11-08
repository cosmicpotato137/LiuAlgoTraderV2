import pandas as pd
import pytest
import toml

from liualgotrader.backtesting import optimizer as backtesting_optimizer
from liualgotrader.backtesting.optimizer import (BacktestSettings,
                                                 backtest_iteration)
from liualgotrader.common.types import AssetType, TimeScale
from liualgotrader.scripts.optimizer import create_backtest_settings


def test_defaults():
    assert create_backtest_settings({}) == BacktestSettings(
        scale=TimeScale.day,
        asset_type=AssetType.US_EQUITIES,
        buy_fee_percentage=0.0,
        sell_fee_percentage=0.0,
    )


def test_all_settings():
    settings = create_backtest_settings(
        {
            "scale": "minute",
            "asset": "Crypto",
            "buy_fee_percentage": 0.25,
            "sell_fee_percentage": 1,
        }
    )

    assert settings == BacktestSettings(
        scale=TimeScale.minute,
        asset_type=AssetType.CRYPTO,
        buy_fee_percentage=0.25,
        sell_fee_percentage=1.0,
    )


@pytest.mark.parametrize(
    "optimizer",
    [
        {"scale": "hour"},
        {"asset": "bonds"},
        {"asset": 1},
        {"buy_fee_percentage": "0.5"},
        {"sell_fee_percentage": True},
    ],
)
def test_invalid_settings(optimizer):
    with pytest.raises(ValueError):
        create_backtest_settings(optimizer)


def test_example_strategy_file():
    spec = toml.load("examples/optimizer/trend_follow.toml")

    assert create_backtest_settings(spec["optimizer"]) == BacktestSettings()


def test_backtest_iteration_uses_settings(monkeypatch):
    calls = []

    async def backtest_main(*args):
        calls.append(args)
        return pd.DataFrame()

    async def save_optimizer_session(*args):
        pass

    monkeypatch.setattr(
        backtesting_optimizer, "configure_logging", lambda: None
    )
    monkeypatch.setattr(
        backtesting_optimizer.enhanced_backtest, "backtest_main", backtest_main
    )
    monkeypatch.setattr(
        backtesting_optimizer.enhanced_backtest,
        "net_cash_flow",
        lambda _: 0.0,
    )
    monkeypatch.setattr(
        backtesting_optimizer, "save_optimizer_session", save_optimizer_session
    )
    settings = BacktestSettings(
        scale=TimeScale.minute,
        asset_type=AssetType.CRYPTO,
        buy_fee_percentage=0.1,
        sell_fee_percentage=0.2,
    )

    backtest_iteration(
        "session",
        pd.Timestamp("2026-01-02").date(),
        pd.Timestamp("2026-01-09").date(),
        [],
        None,
        settings,
    )

    (args,) = calls
    _, _, _, scale, _, buy_fee, sell_fee, asset_type = args
    assert (scale, buy_fee, sell_fee, asset_type) == (
        TimeScale.minute,
        0.1,
        0.2,
        AssetType.CRYPTO,
    )
