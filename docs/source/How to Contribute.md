# Contributing
Would you like to help improve & evolve LiuAlgoTrader?
Do you have a suggestion, comment, idea for improvement or
a have a wish-list item? Please read our
Contribution [Document](https://github.com/amor71/LiuAlgoTrader/blob/master/CONTRIBUTING.md) or email me at <amichay@sgeltd.com>.

## How to setup a development environment

LiuAlgoTrader manages its dependencies with [PDM](https://pdm-project.org). `pyproject.toml` declares
them, and `pdm.lock` pins the exact versions to develop and test with.

Prerequisites:

- Python 3.12 or later,
- PDM, for example installed with `pipx install pdm` or `brew install pdm`.

1. Clone LiuAlgoTrader:

   ```bash
   git clone https://github.com/amor71/LiuAlgoTrader.git
   cd LiuAlgoTrader
   ```

   This checks out the `master` branch, which is the latest development
   version. It may not be the most stable version; the latest stable version
   is the latest tagged version.

2. Install LiuAlgoTrader and the development tools:

   ```bash
   pdm install -G dev
   ```

   PDM creates a virtual environment in `.venv`, installs the locked
   dependencies into it, and installs LiuAlgoTrader in editable mode, along
   with the `liu`, `trader`, `backtester`, `optimizer` and
   `portfolio` commands. To choose the Python
   interpreter, run `pdm use <path to python>` before installing. Prefix
   commands with `pdm run`, or activate the environment with
   `source .venv/bin/activate`.

3. Install the git pre-commit hook:

   ```bash
   pdm run pre-commit install
   ```

   On each commit, the hook runs mypy, bandit, black, isort and autoflake on
   the staged Python files. To run the hooks on other files, use
   `pdm run pre-commit run --files <files>`.

4. Optionally, run the quickstart wizard to check your Alpaca credentials,
   create the default SQLite database and download the samples:

   ```bash
   pdm run liu quickstart
   ```

   Follow [these](https://liualgotrader-v2.readthedocs.io/en/latest/Quickstart.html) instructions, skipping `Step 1`. {doc}`Configuration` lists
   the environment variables that LiuAlgoTrader reads. To work on PostgreSQL
   support, also install its driver with `pdm install -G dev -G postgres`.

5. Run the tests:

   ```bash
   pdm run pytest
   pdm run pytest tests/test_resample.py
   ```

   The tests use a new SQLite database for each run, unless `DSN` names
   another database, such as a PostgreSQL test database. Tests of a
   broker or data provider also need its API keys, such as
   `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` for Alpaca.

To add or upgrade a dependency, run `pdm add <package>` or
`pdm update <package>`, and commit both `pyproject.toml` and `pdm.lock`.
Development tools belong in the `dev` group: `pdm add -G dev <package>`.

To change the database schema, edit the models in `liualgotrader/db/models`,
then generate a migration by comparing them with a database at the latest
migration:

```bash
export DSN=sqlite:////tmp/liu-dev.db
pdm run alembic upgrade head
pdm run alembic revision --autogenerate -m "describe the change"
```

Review the new file in `liualgotrader/db/migrations/versions`: autogenerate
writes a renamed column as a dropped and an added column, and does not move
data, so edit the migration for those. `tests/test_migrations.py` fails
while the models and the migrations differ. LiuAlgoTrader applies new
migrations to a database the next time it uses it.


## Contributors

Special thanks to the below individuals for their comments, reviews and suggestions:

- Jonathan Morland-Barrett [sigmantium](https://github.com/sigmantium)
- Alex Lau [riven314](https://github.com/riven314)
- Rokas Gegevicius [ksilo](https://github.com/ksilo)
- Shlomi Kushchi [shlomikushchi](https://github.com/shlomikushchi)
- Venkat Y [vinmestmant](https://github.com/vinmestmant)
- Chris [crowforc3](https://github.com/crawforc3)
- [TheSnoozer](https://github.com/TheSnoozer)
- Aditya Gupta [adi0x90](https://github.com/adi0x90)
