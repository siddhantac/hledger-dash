import os
from pathlib import Path

os.environ["HLEDGER_FILE"] = str(Path(__file__).resolve().parent.parent / "testdata" / "synthetic.journal")
