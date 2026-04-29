# ============================================================
#  backend/kite_client.py
#  Single authenticated KiteConnect instance for the whole app.
#  All other modules import get_kite() from here.
# ============================================================

import os
from kiteconnect import KiteConnect
from dotenv import load_dotenv
from backend.token_store import load_token

load_dotenv()

_kite: KiteConnect | None = None


def get_kite() -> KiteConnect | None:
    """
    Returns an authenticated KiteConnect instance if a valid
    token exists, otherwise returns None (user needs to login).
    """
    global _kite

    token = load_token()
    if not token:
        _kite = None
        return None

    if _kite is None:
        _kite = KiteConnect(api_key=os.getenv('KITE_API_KEY'))

    _kite.set_access_token(token)
    return _kite


def build_unauthenticated_kite() -> KiteConnect:
    """Used during the login flow before we have an access token."""
    return KiteConnect(api_key=os.getenv('KITE_API_KEY'))


def is_authenticated() -> bool:
    return get_kite() is not None
