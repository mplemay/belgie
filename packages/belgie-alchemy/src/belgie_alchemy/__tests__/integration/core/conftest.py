import sys
from pathlib import Path

PACKAGES_ROOT = Path(__file__).resolve().parents[6]
OAUTH_CLIENT_SRC = PACKAGES_ROOT / "belgie-oauth" / "src"
if str(OAUTH_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(OAUTH_CLIENT_SRC))
