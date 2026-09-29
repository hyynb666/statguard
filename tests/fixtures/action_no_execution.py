"""This file is a static-analysis fixture and must never be executed."""

import os
from pathlib import Path

Path(os.environ["STATGUARD_MARKER"]).touch()
