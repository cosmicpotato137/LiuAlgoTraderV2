.. _`How to Install & Setup`:

Advanced Setup
==============

This section describes the steps to
install and setup `LiuAlgoTrader` for first time use, including on a PostgreSQL database server. The section is mostly relevant for users that did not go through the `Quickstart` wizard.

Prerequisite
------------
- Paper, or a funded Live account with `Alpaca Markets`_ ,
- Optionally, a PostgreSQL_ database server. Without one, LiuAlgoTrader uses a local SQLite database.

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
The database is mostly used for storing trade details, including stock name, price, quantity,
indicators and more. This data is valuable when analysing the trading day,
and improving the algorithmic strategies. For further reading, see Understanding the Data Model.

By default, the database is a SQLite file at `~/.liualgotrader/liu.db`, which
needs no installation or configuration. PostgreSQL is supported as well, and
suits a database shared by several machines, or many trading processes writing
at once, better.

Database Connection
*******************

The **DSN** environment variable holds the URL of the database; leave it unset
for the default SQLite database. For example:

.. code-block:: bash

    export DSN="sqlite:////path/to/liu.db"
    export DSN="postgresql://momentum@localhost/tradedb"

PostgreSQL needs its database driver, installed as an extra:

.. code-block:: bash

    pip install 'liualgotrader[postgres]'

A `postgresql://` DSN is a libpq `connection URI`_, so it accepts parameters
such as `sslmode`, and takes any missing part from the `PG*` environment
variables. Any other DSN is a SQLAlchemy `database URL`_.

.. _connection URI: https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING-URIS
.. _database URL: https://docs.sqlalchemy.org/en/20/core/engines.html#database-urls

Database Schema
***************

LiuAlgoTrader creates and upgrades the database schema itself: the first time a
process uses a database, it applies the migrations that the database is missing.
Databases created by versions before migrations are not supported. A PostgreSQL
database and its user must already exist.

Data Providers
--------------
Algorithmic trading is only as good as the data feed it rely on.
Without an accurate, near-real-time data feed even the
best strategy will keep losing money.

LiuAlgoTrader currently support Polygon.io as a data-provider, as well as 
Alapaca native data integration. Additional integration are underway (Finnhub_).


.. _Finnhub: https://finnhub.io/dashboard
