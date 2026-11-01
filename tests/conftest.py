import atexit
import os
import shutil
import tempfile
import warnings
from collections import Counter

import pytest
from dotenv import load_dotenv

load_dotenv()

# Unless DSN names a database, run the tests against a new SQLite database
# rather than the default one. Set before liualgotrader.common.config reads it.
if not os.getenv("DSN"):
    _db_dir = tempfile.mkdtemp(prefix="liualgotrader-tests-")
    atexit.register(shutil.rmtree, _db_dir, ignore_errors=True)
    os.environ["DSN"] = f"sqlite:///{os.path.join(_db_dir, 'liu.db')}"

# The settings each vendor's API credentials consist of, as the attribute of
# its liualgotrader.common.config object and the environment variable that
# sets it.
_CREDENTIALS = {
    "alpaca": [
        ("api_key", "APCA_API_KEY_ID"),
        ("api_secret", "APCA_API_SECRET_KEY"),
    ],
    "gemini": [
        ("api_key", "GEMINI_API_KEY"),
        ("api_secret", "GEMINI_API_SECRET"),
    ],
    "tradier": [
        ("access_token", "TRADIER_ACCESS_TOKEN"),
        ("account_number", "TRADIER_ACCOUNT_NUMBER"),
    ],
}


def pytest_collection_modifyitems(config, items):
    """Skip the tests whose vendor credentials are not configured.

    A test marked requires_credentials(vendor) is skipped unless every
    credential of the vendor is set, and one warning per vendor names the
    missing environment variables.

    Parameters
    ----------
    config: pytest.Config
        The pytest configuration, which is not used.
    items: List[pytest.Item]
        The collected tests.
    """
    from liualgotrader.common import config as liu_config

    skipped: Counter = Counter()
    for item in items:
        for marker in item.iter_markers("requires_credentials"):
            vendor = marker.args[0]
            missing = tuple(
                variable
                for attribute, variable in _CREDENTIALS[vendor]
                if not getattr(getattr(liu_config, vendor), attribute)
            )
            if missing:
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"no {vendor} credentials: set "
                        + " and ".join(missing)
                    )
                )
                skipped[vendor, missing] += 1

    for (vendor, missing), count in skipped.items():
        warnings.warn(
            f"skipped {count} test{'s' if count > 1 else ''} that need "
            f"{vendor} credentials; set {' and '.join(missing)} to run them"
        )
