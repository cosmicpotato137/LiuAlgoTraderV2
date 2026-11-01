# A scalable algorithmic trading framework

## Overview

**LiuAlgoTrader** is a scalable, multi-process framework
for effective algorithmic trading. The framework is
intended to simplify development, testing,
deployment, backtesting and evaluating algo trading strategies.

The framework currently support trading and back-testing of US Equities, and Crypto strategies.

LiuAlgoTrader can run on a laptop and *hedge-on-the-go*, or run on a multi-core hosted Linux server and it will automatically optimize for best performance for either. LiuAlgoTrader is a full trading platform with a breath of tools to manage automated investment portfolios.

LiuAlgoTrader supports:

* [Alpaca.Markets](https://alpaca.markets/)  APIs for trading, and data loading & streaming,

* [Gemini](https://www.gemini.com/) Crypto Exchange APIs for trading, data loading & streaming,

* [Polygon.io](https://polygon.io/) APIs for data-loading, and streaming,

* (**BETA**) [Tradier](https://tradier.com/) APIs for trading and data loadinng


LiuAlgoTrader can run on a laptop and
*hedge-on-the-go*, or run on a multi-core hosted Linux server
and it will optimize for best performance for either. The framework runs on Linux, Mac OS or, Windows.

LiuAlgoTrader is made of the following components:

- **trader**: the main application for real-time trading,
- **backtester**: re-running past trading sessions, back-testing strategies,
- **optimizer**: application for optimizing strategies' hyper-parameters.
- **portfolio**: application for managing & tracking portfolios.

AND

- **streamlit apps** & **analysis notebooks**: collection of visual applications and notebooks for analysis of trading sessions, backtesting, as well as various tools for improving trading algos.

The rest of the documentation explains how to install,
setup, configure and run trading & analysis
sessions w/ LiuAlgoTrader.


```{toctree}
:maxdepth: 2

What's New
Quickstart
Getting Started
Tutorials
(Advanced) Setup
Concepts
Configuration
Crypto
Filters
Strategies
Trading
Backtesting
Additional apps
Analysis
How to Contribute
Troubleshooting
```


# Indices and tables

* {ref}`genindex`
* {ref}`modindex`
* {ref}`search`
