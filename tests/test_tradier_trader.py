import asyncio
import logging
import time
from datetime import date, timedelta

import pytest

from liualgotrader.common import config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.types import DataConnectorType, Order, TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.tradier.trader import TradierTrader

logger = logging.getLogger(__name__)

tradier_trader: TradierTrader


@pytest.fixture(autouse=True)
async def db_connection():
    global tradier_trader
    await create_db_connection()
    tradier_trader = TradierTrader(config.tradier)


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_get_symbols():
    logger.info("test_get_symbols")
    assets = await tradier_trader.get_tradeable_symbols()
    logger.info("%s", assets)
    logger.info("%s", len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_get_shortable_symbols():
    logger.info("test_get_shortable_symbols")
    assets = await tradier_trader.get_shortable_symbols()
    logger.info("%s", assets)
    logger.info("%s", len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_is_aapl_shortable():
    logger.info("test_is_aapl_shortable")
    shortable = await tradier_trader.is_shortable("AAPL")

    if not shortable:
        raise AssertionError("expected AAPL to be shortable")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_is_fractionable():
    logger.info("test_is_fractionable")
    apa_fractionable = await tradier_trader.is_fractionable("APA")
    if not apa_fractionable:
        logger.info("APA is not fractionable")
    aapl_fractionable = await tradier_trader.is_fractionable("AAPL")
    if not aapl_fractionable:
        logger.info("AAPL is not fractionable ")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_market_schedule():
    logger.info("test_get_market_schedule")
    start, end = tradier_trader.get_market_schedule()
    logger.info("market open %s close %s", start, end)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_is_market_open_today():
    logger.info("test_is_market_open_today")
    is_open = tradier_trader.is_market_open_today()
    logger.info("Market open today %s", is_open)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_time_market_close():
    logger.info("test_get_time_market_close")
    when_close = tradier_trader.get_time_market_close()
    logger.info("Market close today %s", when_close)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_trading_days():
    logger.info("test_get_trading_days")
    td = tradier_trader.get_trading_days(
        start_date=date.today(), end_date=date.today()
    )
    logger.info("trading days %s", td)

    logger.info("test_get_trading_days")
    td = tradier_trader.get_trading_days(
        start_date=date.today() - timedelta(days=5), end_date=date.today()
    )
    logger.info("trading days %s", td)

    logger.info("test_get_trading_days")
    td = tradier_trader.get_trading_days(
        start_date=date.today() - timedelta(days=65), end_date=date.today()
    )
    logger.info("trading days %s", td)
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_aapl_order_market_long():
    logger.info("test_aapl_order_market_long")

    open_position = tradier_trader.get_position(symbol="AAPL")
    logger.info("Open position in Apple is %s", open_position)
    try:
        order = await tradier_trader.submit_order(
            symbol="AAPL", qty=10, side="buy", order_type="market"
        )
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)
        return True

    logger.info("submitted order: %s", order)

    for _ in range(5):
        order = await tradier_trader.get_order(order_id=order.order_id)
        logger.info("pulled order: %s", order)

        if order.remaining_amount == 0.0:
            break
        time.sleep(0.5)

    position = tradier_trader.get_position(symbol="AAPL")

    logger.info("New position in Apple is %s", position)

    try:
        order = await tradier_trader.submit_order(
            symbol="AAPL", qty=10, side="sell", order_type="market"
        )
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)
        return True

    logger.info("submitted order: %s", order)

    for _ in range(5):
        order = await tradier_trader.get_order(order_id=order.order_id)
        logger.info("pulled order: %s", order)

        if order.remaining_amount == 0.0:
            break
        time.sleep(0.5)

    position = tradier_trader.get_position(symbol="AAPL")
    logger.info("New position in Apple is %s", position)

    if position != open_position:
        raise AssertionError(
            "position after buy & sell was supposed to be same as open position"
        )
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_aapl_order_limit_long():
    logger.info("test_aapl_order_limit_long")

    open_position = tradier_trader.get_position(symbol="AAPL")
    logger.info("Open position in Apple is %s", open_position)

    dl = DataLoader(connector=DataConnectorType.tradier)

    last_price = dl["AAPL"].close[-1]

    logger.info("last_price= %s", last_price)
    logger.info("%s", dl["AAPL"].close)
    try:
        order = await tradier_trader.submit_order(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type="limit",
            limit_price=last_price,
        )
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)
        return True
    logger.info("submitted order: %s", order)
    success = False
    for _ in range(5):
        order = await tradier_trader.get_order(order_id=order.order_id)
        logger.info("pulled order: %s", order)

        if order.remaining_amount == 0.0:
            success = True
            break
        time.sleep(0.5)

    position = tradier_trader.get_position(symbol="AAPL")

    if success:
        time.sleep(10.0)
        logger.info("New position in Apple is %s", position)

        last_price = dl["AAPL"].close[-1]
        logger.info("last_price= %s", last_price)
        try:
            order = await tradier_trader.submit_order(
                symbol="AAPL",
                qty=10,
                side="sell",
                order_type="limit",
                limit_price=last_price,
            )
        except ValueError as e:
            logger.info("ValueError Exception : %s", e)
            return True

        logger.info("submitted order: %s", order)

        for _ in range(5):
            order = await tradier_trader.get_order(order_id=order.order_id)
            logger.info("pulled order: %s", order)

            is_filled, _, _, _ = await tradier_trader.is_order_completed(
                order_id=order.order_id
            )
            logger.info("is_filled %s", is_filled)
            if is_filled == Order.EventType.fill:
                break
            time.sleep(0.5)

        position = tradier_trader.get_position(symbol="AAPL")
        logger.info("New position in Apple is %s", position)

        if position != open_position:
            raise AssertionError(
                "position after buy & sell was supposed to be same as open position"
            )

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_tsla_order_market_short():
    logger.info("test_tsla_order_market_short")

    open_position = tradier_trader.get_position(symbol="TSLA")
    logger.info("Open position in Tesla is %s", open_position)

    try:
        order = await tradier_trader.submit_order(
            symbol="TSLA", qty=10, side="sell_short", order_type="market"
        )
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)
        return True
    logger.info("submitted order: %s", order)

    sold = False
    for _ in range(5):
        order = await tradier_trader.get_order(order_id=order.order_id)
        logger.info("pulled order: %s", order)

        is_filled, _, _, _ = await tradier_trader.is_order_completed(
            order_id=order.order_id
        )

        logger.info("is_filled %s", is_filled)
        if is_filled == Order.EventType.fill:
            sold = True
            break

        time.sleep(0.5)

    if sold:
        position = tradier_trader.get_position(symbol="TSLA")
        logger.info("New position in is %s", position)

        try:
            order = await tradier_trader.submit_order(
                symbol="TSLA", qty=10, side="buy_to_cover", order_type="market"
            )
        except ValueError as e:
            logger.info("ValueError Exception : %s", e)
            return True
        logger.info("submitted order: %s", order)

        for _ in range(5):
            order = await tradier_trader.get_order(order_id=order.order_id)
            logger.info("pulled order: %s", order)

            is_filled, _, _, _ = await tradier_trader.is_order_completed(
                order_id=order.order_id
            )
            logger.info("is_filled %s", is_filled)
            if is_filled == Order.EventType.fill:
                break

            time.sleep(0.5)

        position = tradier_trader.get_position(symbol="TSLA")
        logger.info("New position is %s", position)

        if position != open_position:
            raise AssertionError(
                "position after buy & sell to be same as open position"
            )

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_tsla_cancel_order():
    logger.info("test_tsla_cancel_order")

    try:
        order = await tradier_trader.submit_order(
            symbol="AAPL", qty=10, side="buy", order_type="market"
        )
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)
        return True
    logger.info("submitted order: %s", order)

    try:
        cancelled = await tradier_trader.cancel_order(order)
        logger.info("cancelled= %s", cancelled)
    except Exception as e:
        logger.info("[EXCEPTION] %s", e)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("tradier")
async def test_aapl_order_limit_long_websocket():
    logger.info("test_aapl_order_limit_long_websocket")

    task_id = await tradier_trader.run()
    logger.info("task_id %s created", task_id)
    await asyncio.sleep(1.0)

    open_position = tradier_trader.get_position(symbol="AAPL")
    logger.info("Open position in Apple is %s", open_position)

    dl = DataLoader(connector=DataConnectorType.tradier)
    last_price = dl["AAPL"].close[-1]

    logger.info("last_price= %s", last_price)
    logger.info("%s", dl["AAPL"].close)
    try:
        order = await tradier_trader.submit_order(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type="limit",
            limit_price=last_price,
        )

        logger.info("submitted order: %s", order)
        order = await tradier_trader.get_order(order_id=order.order_id)
        logger.info("pulled order: %s", order)
    except ValueError as e:
        logger.info("ValueError Exception : %s", e)

    await asyncio.sleep(60.0)
    await tradier_trader.close()

    return True
