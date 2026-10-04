import atexit
import os
import shutil
import tempfile

# Unless DSN names a database, run the tests against a new SQLite database
# rather than the default one. Set before liualgotrader.common.config reads it.
if not os.getenv("DSN"):
    _db_dir = tempfile.mkdtemp(prefix="liualgotrader-tests-")
    atexit.register(shutil.rmtree, _db_dir, ignore_errors=True)
    os.environ["DSN"] = f"sqlite:///{os.path.join(_db_dir, 'liu.db')}"
