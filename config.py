import json
import os
from datetime import timedelta
from pathlib import Path


def _load_specs() -> dict:
    default_path = Path(__file__).with_name("specs.json")
    specs_path = Path(os.getenv("SPECS_PATH", default_path))
    if not specs_path.exists():
        raise FileNotFoundError(f"Specs file not found at {specs_path}")

    with specs_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


SPECS = _load_specs()


class Config:
    """Base configuration for the subscription demo application."""

    _mongo = SPECS.get("mongo", {})
    _plans = SPECS.get("plans", {})

    FLASK_DEBUG = bool(SPECS.get("flask_debug", False))
    SECRET_KEY = SPECS.get("secret_key", "change-this-secret-key")

    MONGO_URI = _mongo.get("uri", "mongodb://localhost:27017")
    MONGO_DB_NAME = _mongo.get("db_name", "subscription_demo")

    JWT_SECRET_KEY = SPECS.get("jwt_secret_key", "change-this-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=float(SPECS.get("jwt_access_token_hours", 1)))

    DEFAULT_PLAN = SPECS.get("default_plan", "starter")
    FALLBACK_RATE_LIMIT = SPECS.get("fallback_rate_limit", "5 per minute")

    SUBSCRIPTION_PLANS = _plans

    LIMITER_STORAGE_URI = SPECS.get("limiter_storage_uri", "memory://")


class TestConfig(Config):
    """Test configuration with shorter expirations and in-memory DB."""

    FLASK_DEBUG = True
    MONGO_URI = "mongodb://localhost:27017"
    MONGO_DB_NAME = "subscription_demo_test"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)


