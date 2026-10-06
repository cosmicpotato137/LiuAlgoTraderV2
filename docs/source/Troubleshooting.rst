Installation FAQ
================


Q : Can I Run Liu on Windows?
-----------------------------

I have a Windows-based environment. Can I use `LiuAlgoTrader`?
 
Answer
******
 
Yes. While `LiuAlgoTrader` is developed & tested on macOS and Linux (Debian), Liu can run on Windows with few minor adaptations.
 
**Database Prerequisites**
 
LiuAlgoTrader keeps its data in a SQLite database by default, which works on Windows as is,
so there is nothing to install.
 
**Trading Setup**
 
It is OK to use Windows to develop strategies, but it is recommended to use Linux once you're ready to
move past back-testing. It is also recommended for the `production` environment to use a
dedicated PostgreSQL server (local, hosted, or managed) rather than the default SQLite database.
 
**Running Liu applications**
 
`pip install liualgotrader` installs 5 applications: **liu**, **trader**, **backtester**, **optimizer**
and **portfolio**. On Windows, they are installed as `.exe` files in the `Scripts` folder of
the Python environment, so you can run them by name once the environment is activated.
 
For example, assuming you have Python 3.12 or later installed on your Windows machine, follow the steps below to
create a dedicated `virtual environment` for Liu:
 
 .. code-block:: bash

    python -m venv liu
    liu\Scripts\activate
    pip install liualgotrader
    liu quickstart

Good Luck!

**Windows Note:** The command that sets an environment variable, such as DSN, depends on your shell.

**Example:**

Use this for Gitbash:

 .. code-block:: bash

    export DSN=connectionString

Use this for Windows PowerShell:

 .. code-block:: bash

    $env:VARIABLE_NAME=VALUE

Q : How to install on Ubuntu?
-----------------------------

I would like to install `liu` on Ubuntu. Can you please list the steps I need to take?

Answer
******

**STEP 1**: Install Python 3.12 or later and basic tools

Ubuntu 24.04 and later include a supported Python:

.. code-block:: bash

    $ sudo apt update
    $ sudo apt install python3 python3-pip python3-venv

On older releases, install a newer Python from the deadsnakes PPA, and use
`python3.14` instead of `python3` in STEP 2:

.. code-block:: bash

    $ sudo add-apt-repository ppa:deadsnakes/ppa
    $ sudo apt update
    $ sudo apt install python3.14 python3.14-venv

**STEP 2**: Install LiuAlgoTrader 

.. code-block:: bash

    $ python3 -m venv liu
    $ source liu/bin/activate
    (liu) $ mkdir liu-dev ; cd liu-dev
    (liu) $ pip install liualgotrader


**STEP 3**: Run installation wizard

    *make sre you have environment keys properly selected*

.. code-block:: bash    

    (liu) $ liu quickstart

