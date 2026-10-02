import pytest

from liualgotrader.common import config
from liualgotrader.db.session import create_db_connection
from liualgotrader.vendors.alpaca.trader import AlpacaTrader

alpaca_trader: AlpacaTrader


@pytest.fixture(autouse=True)
async def db_connection():
    global alpaca_trader
    await create_db_connection()
    alpaca_trader = AlpacaTrader(config.alpaca)


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_symbols():
    global alpaca_trader
    assets = await alpaca_trader.get_tradeable_symbols()
    print(assets)
    print(len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_get_shortable_symbols():
    global alpaca_trader
    assets = await alpaca_trader.get_shortable_symbols()
    print(assets)
    print(len(assets))
    return True


@pytest.mark.asyncio
@pytest.mark.devtest
async def test_is_fractionable():
    global alpaca_trader
    apa_fractionable = await alpaca_trader.is_fractionable("APA")
    print("APA:", apa_fractionable)

    if not apa_fractionable:
        print("APA is not fractionable")
    aapl_fractionable = await alpaca_trader.is_fractionable("AAPL")
    print("AAPL:", aapl_fractionable)
    if not aapl_fractionable:
        print("AAPL is fractionable ")

    return True
