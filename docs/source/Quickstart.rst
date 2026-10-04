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

The backtester prints the batch-id of the session. Then run the back-test UI:

.. code-block:: bash

    streamlit run https://raw.github.com/amor71/LiuAlgoTrader/master/analysis/backtester_ui.py

Once executed, your screen should look like this:

.. image:: /images/liu-firsttime.png
    :width: 800
    :align: left
    :alt: liu first time use


Select the `Analyzer` app on the upper-right drop-down and enter the batch-id
of your back-test.

`Voila!`
^^^^^^^^
You should see your back-test session, loaded from your local database.
You're all set now.

**NOTE**

Back-testing a whole day requires downloading market data for that day, which
may take minutes to an hour depending on your connection type.

The Database
------------

LiuAlgoTrader keeps track of your trading in a SQLite database at
`~/.liualgotrader/liu.db`, and creates its tables on first use. See
`Database Setup`_ for using a PostgreSQL server instead.

.. _Database Setup: https://liualgotrader-v2.readthedocs.io/en/latest/(Advanced)%20Setup.html#database-setup

What's Next?
------------

Read through the rest of the documentation, starting with the 'Getting Started' section. Understand the framework concepts, create your own strategies and run a trading session.