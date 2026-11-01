**Quickstart**
==============

Prerequisite
------------

1. Python 3.12 or later,

2. Paper, or a funded account with Alpaca_ Markets.

.. _Alpaca: https://alpaca.markets/docs/about-us


Touch & Go
----------

**NOTE** for Windows_ users

.. _Windows: https://liualgotrader-v2.readthedocs.io/en/latest/Troubleshooting.html#q-can-i-run-liu-on-windows

**Step 1**: install LiuAlgoTrader

.. code-block:: bash

   pip install liualgotrader

Having issues on installation? Check out the installation FAQ_

.. _FAQ: https://liualgotrader-v2.readthedocs.io/en/latest/Troubleshooting.html

**Step 2**: Run the setup wizard

.. code-block:: bash

   liu quickstart

Follow the installation wizard instructions. The wizard checks your Alpaca
credentials, creates the database and downloads the samples:

.. image:: /images/liu-wizard.png
    :width: 800
    :align: left
    :alt: liu setup wizard


First time use
--------------

LiuAlgoTrader `quickstart` wizard installs samples allowing a first-time experience of the framework. Follow the post-installation instructions, and try to back-test a specific day
from within the samples directory:

.. code-block:: bash

    backtester from 2026-09-01

The backtester prints the batch-id of the session when it completes.

**NOTE**: the samples that the wizard downloads may still use the
`[scanners]` and `[strategies]` trade plan sections of earlier
releases. If the `backtester` rejects them, use the samples in the
`examples` folder of the GitHub repository, which use the
`[filters]`, `[signals]` and `[rules]` sections explained in the
`Strategies` section.

`Voila!`
^^^^^^^^
You should find your back-test session in two files in the current
directory: `<batch-id>-trades.csv`, with one row per trade, and
`<batch-id>-summary.txt`, with the results of each rule.
You're all set now.

**NOTE**

Back-testing a whole day requires downloading market data for that day, which
may take minutes to an hour depending on your connection type.

The Database
------------

LiuAlgoTrader keeps its data, such as portfolios and the stocks picked by
filters, in a SQLite database at `~/.liualgotrader/liu.db`, and creates its
tables on first use. See
`Database Setup`_ for using a PostgreSQL server instead.

.. _Database Setup: https://liualgotrader-v2.readthedocs.io/en/latest/(Advanced)%20Setup.html#database-setup

What's Next?
------------

Read through the rest of the documentation, starting with the 'Getting Started' section. Understand the framework concepts, create your own filters, signals and rules, and run a trading session.