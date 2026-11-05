"""Vendor implementations of the trader, data and streaming interfaces.

Each subpackage holds a vendor's connection settings in config and its
implementations of TraderAPI in trader, DataAPI in data, MarketCalendarAPI in
market_calendar and StreamingAPI in streaming, as far as the vendor supports
them.

Subpackages
-----------
alpaca
    Alpaca brokerage, market data, market calendar and streaming.
finnhub
    Finnhub market data.
gemini
    Gemini cryptocurrency exchange, market data and streaming.
polygon
    Polygon market data and streaming.
tradier
    Tradier brokerage and market data.
"""
