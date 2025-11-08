from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager, get_jwt_identity


jwt = JWTManager()


def _rate_limit_key_func():
    """Use the JWT identity when available, otherwise fall back to the IP address."""

    try:
        identity = get_jwt_identity()
    except RuntimeError:
        identity = None

    return identity or get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key_func,
    default_limits=[],
)

