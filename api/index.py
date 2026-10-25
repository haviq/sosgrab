import os

os.environ.setdefault("LOG_DIR", "/tmp")

from server import app  # noqa: E402, F401
