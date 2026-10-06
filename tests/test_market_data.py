import logging
import time
from datetime import date

import pandas as pd
import pytest

from liualgotrader.common import clock, config
from liualgotrader.common.data_loader import DataLoader  # type: ignore
from liualgotrader.common.market_data import (get_industries_tickers,
                                              get_market_industries,
                                              get_market_sectors,
                                              get_sectors_tickers,
                                              get_trading_day,
                                              get_trading_holidays,
                                              sp500_historical_constituents)
from liualgotrader.common.types import TimeScale
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.alpaca.trader import AlpacaTrader

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def db_connection():
    await create_db_connection()


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_market_industries():
    industry_list = await get_market_industries()

    logger.info("%s", industry_list)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_market_sectors():
    sector_list = await get_market_sectors()
    logger.info("%s", sector_list)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_market_sectors_symbols():
    sector_list = await get_market_sectors()

    l = await get_sectors_tickers(sector_list)
    logger.info("sectors_tickers %s", l)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_market_industries_symbols():
    industries_list = await get_market_industries()
    l = await get_industries_tickers(industries_list)
    logger.info("%s", l)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_sp500_historical_constituents():
    sp500_symbols = await sp500_historical_constituents(clock.today())
    logger.info("%s", sp500_symbols)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_trading_holidays():
    holidays = await get_trading_holidays()

    logger.info("%s", holidays)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("alpaca")
async def test_get_trading_day():
    alpaca = AlpacaTrader(config.alpaca)
    today = clock.today()

    d1 = await get_trading_day(now=today, offset=1)
    logger.info("%s", d1)
    _df = alpaca.get_trading_days(d1, today)

    if len(_df.index) < 1 or len(_df.index) > 2:
        raise AssertionError("expected offset 1")

    d1 = await get_trading_day(now=today, offset=40)
    logger.info("%s", d1)
    _df = alpaca.get_trading_days(d1, today)

    if len(_df.index) < 40 or len(_df.index) > 41:
        raise AssertionError("expected offset 40")

    d1 = await get_trading_day(now=today, offset=100)
    logger.info("%s", d1)
    _df = alpaca.get_trading_days(d1, today)

    if len(_df.index) < 100 or len(_df.index) > 101:
        raise AssertionError("expected offset 100")

    d1 = await get_trading_day(now=today, offset=300)
    logger.info("%s", d1)
    _df = alpaca.get_trading_days(d1, today)

    if len(_df.index) < 300 or len(_df.index) > 301:
        raise AssertionError("expected offset 300")

    d1 = await get_trading_day(now=today, offset=1000)
    logger.info("%s", d1)
    _df = alpaca.get_trading_days(d1, today)
    if len(_df.index) < 1000 or len(_df.index) > 1001:
        raise AssertionError("expected offset 1000")

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_load_basic_sp500():
    today = clock.today()
    sp500_symbols = await sp500_historical_constituents(today)

    logger.info("%s", sp500_symbols)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_load_sp500_data_w_adjustments():

    sp500_symbols = await sp500_historical_constituents(date(2019, 1, 11))
    logger.info("%s", sp500_symbols)

    return True


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("alpaca")
async def test_load_sp500_data():

    today = clock.today()
    sp500_symbols = await sp500_historical_constituents(today)
    logger.info("%s", sp500_symbols)
    dl = DataLoader(scale=TimeScale.day)
    d1 = await get_trading_day(now=today, offset=200)

    logger.info("start:%s, end:%s", d1, today)
    span = slice(
        pd.Timestamp(d1, tz=clock.NY), pd.Timestamp(today, tz=clock.NY)
    )
    t0 = time.time()
    dl.pre_fetch(symbols=sp500_symbols, start=d1, end=today)
    t = time.time() - t0
    logger.info("loaded SP500 in %s", t)

    t0 = time.time()
    dl[sp500_symbols[0]][span]
    t = time.time() - t0
    logger.info("loaded first symbol in %s", t)
    logger.info("%s %s", sp500_symbols[0], dl[sp500_symbols[0]][span])

    t0 = time.time()
    dl[sp500_symbols[-1]][span]
    t = time.time() - t0
    logger.info("loaded last symbol in %s", t)
    logger.info("%s %s", sp500_symbols[-1], dl[sp500_symbols[-1]][span])


@pytest.mark.asyncio
@pytest.mark.devtest
@pytest.mark.requires_credentials("alpaca")
async def test_load_sp500_data_minute():
    today = clock.today()
    sp500_symbols = await sp500_historical_constituents(today)
    dl = DataLoader(scale=TimeScale.minute)
    d1 = await get_trading_day(now=today, offset=10)

    logger.info("start:%s, end:%s", d1, today)
    span = slice(
        pd.Timestamp(d1, tz=clock.NY), pd.Timestamp(today, tz=clock.NY)
    )
    t0 = time.time()
    dl.pre_fetch(symbols=sp500_symbols, start=d1, end=today)
    t = time.time() - t0
    logger.info("loaded SP500 in %s", t)

    t0 = time.time()
    dl[sp500_symbols[0]][span]
    t = time.time() - t0
    logger.info("loaded first symbol in %s", t)
    logger.info("%s %s", sp500_symbols[0], dl[sp500_symbols[0]][span])

    t0 = time.time()
    dl[sp500_symbols[-1]][span]
    t = time.time() - t0
    logger.info("loaded last symbol in %s", t)
    logger.info("%s %s", sp500_symbols[-1], dl[sp500_symbols[-1]][span])
