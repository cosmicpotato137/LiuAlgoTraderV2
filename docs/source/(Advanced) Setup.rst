.. _`How to Install & Setup`:

Advanced Setup
==============

This section describes the steps to
install and setup `LiuAlgoTrader` for first time use on a pre-existing PostgreSQL database installation. The section is mostly relevant for users that did not go through the `Quickstart` wizard.

Prerequisite
------------
- Paper, or a funded Live account with `Alpaca Markets`_ ,
- An Installed and configured PostgreSQL_ database.

.. _Alpaca Markets: https://alpaca.markets/docs/about-us/
.. _PostgreSQL: https://www.postgresql.org/

Data Sources
------------
LiuAlgoTrader supports both Alpaca and Polygon.io as data-sources, 
however Alpaca data offering has a more limited functionality.

When using Polygon.io A `Stater`, or above subscription w/ Polygon_ is required.

.. _Polygon: https://polygon.io/pricing

Alpaca is the default data-provider, Unlimited/Pro subscription is recommanded.

Installation
------------

LiuAlgoTrader requires Python 3.12 or later. To install LiuAlgoTrader type:

.. code-block:: bash

   pip install liualgotrader

Database Setup
--------------

LiuAlgoTrader applications persist trade details to a relational database.
The applications are developed on-top of PostgreSQL_, however the code may be adopted to use any SQL-supported database .


The database is mostly used for storing trade details, including stock name, price, quantity,
indicators and more. This data is valuable when analysing the trading day,
and improving the algorithmic strategies. For further reading, see Understanding the Data Model.

Database Connection
*******************

The **DSN** environment variable holds the connection string to the database. For example:

.. code-block:: bash

    export DSN="postgresql://momentum@localhost/tradedb"

To `learn more`_ on how to select your connection string.

.. _learn more: https://www.postgresql.org/docs/9.3/libpq-connect.html#LIBPQ-CONNSTRING


Database Schema script
**********************

The following SQL script creates the required database schema:

.. literalinclude:: ../../database/schema.sql
  :linenos:


**NOTE**:
When updating from a predecessor version of `LiuAlgoTrader`, it is recommended to re-run the database script.
the latest schema file can be found in the `database` folder in LiuAlgoTrader distribution.
The script is backward compatible and executing the scripts will automatically
migrate the data to the latest version.

Data Providers
--------------
Algorithmic trading is only as good as the data feed it rely on.
Without an accurate, near-real-time data feed even the
best strategy will keep losing money.

LiuAlgoTrader currently support Polygon.io as a data-provider, as well as 
Alapaca native data integration. Additional integration are underway (Finnhub_).


.. _Finnhub: https://finnhub.io/dashboard
