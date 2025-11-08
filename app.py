from datetime import datetime, timezone

from bson import ObjectId
from flask import Flask, abort, current_app, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash
from flask_jwt_extended import (
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from limits import parse as parse_limit

from config import Config
from database import close_client, get_db
from extensions import jwt, limiter


FEATURE_ENDPOINTS = {
    "alpha": "feature_alpha",
    "beta": "feature_beta",
    "gamma": "feature_gamma",
}


FEATURE_LABELS = {
    "alpha": "Alpha Insights",
    "beta": "Beta Analytics",
    "gamma": "Gamma Automation",
}


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    jwt.init_app(app)
    app.config.setdefault("RATELIMIT_STORAGE_URI", app.config["LIMITER_STORAGE_URI"])
    limiter.init_app(app)

    app.teardown_appcontext(close_client)

    with app.app_context():
        ensure_indexes()

    register_routes(app)
    register_error_handlers(app)

    return app


def ensure_indexes() -> None:
    users = get_user_collection()
    users.create_index("email", unique=True)


def get_user_collection():
    return get_db()["users"]


def serialize_user(user: dict) -> dict:
    user_id = user.get("id") or user.get("_id")
    if user_id is not None:
        user_id = str(user_id)

    return {
        "id": user_id,
        "email": user.get("email"),
        "plan": user.get("plan"),
        "created_at": user.get("created_at"),
    }


def get_user_by_id(user_id: str) -> dict | None:
    try:
        object_id = ObjectId(user_id)
    except Exception:  # noqa: BLE001 - catching invalid ObjectId
        return None

    return get_user_collection().find_one({"_id": object_id})


def get_user_from_request() -> dict | None:
    if hasattr(g, "current_user"):
        return g.current_user

    identity = None
    try:
        identity = get_jwt_identity()
    except RuntimeError:
        return None

    if identity is None:
        return None

    document = get_user_by_id(identity)
    if not document:
        g.current_user = None
        return None

    user = {
        "id": str(document["_id"]),
        "email": document.get("email"),
        "plan": document.get("plan"),
        "created_at": document.get("created_at"),
        "_object_id": document["_id"],
    }

    g.current_user = user
    return user


def resolve_plan(plan_key: str | None) -> tuple[str, dict]:
    default_key = current_app.config["DEFAULT_PLAN"]
    plans = current_app.config["SUBSCRIPTION_PLANS"]
    key = plan_key or default_key
    plan = plans.get(key)
    if not plan:
        key = default_key
        plan = plans[default_key]
    return key, plan


def limit_for(feature_key: str):
    def _limit() -> str:
        plan_key, plan = resolve_plan(None)

        user = get_user_from_request()
        if user:
            plan_key, plan = resolve_plan(user.get("plan"))

        limits = plan.get("limits", {})
        return limits.get(feature_key, current_app.config["FALLBACK_RATE_LIMIT"])

    return _limit

def _limit_identifiers(limit_key: str | None, scope: str) -> list[str]:
    if not limit_key:
        return []

    identifiers = [limit_key, scope]
    key_prefix = getattr(limiter, "_key_prefix", None)
    if key_prefix:
        identifiers.insert(0, key_prefix)

    return identifiers


def _collect_usage_snapshot(limit_key: str | None, endpoint: str, limit_string: str | None) -> dict:
    if not limit_key or not limit_string:
        return {
            "limit": limit_string,
            "capacity": None,
            "remaining": None,
            "used": None,
            "window_seconds": None,
            "resets_at": None,
        }

    try:
        limit_item = parse_limit(limit_string)
    except Exception:
        return {
            "limit": limit_string,
            "capacity": None,
            "remaining": None,
            "used": None,
            "window_seconds": None,
            "resets_at": None,
        }

    identifiers = _limit_identifiers(limit_key, endpoint)
    if not identifiers:
        return {
            "limit": limit_string,
            "capacity": int(limit_item.amount),
            "remaining": int(limit_item.amount),
            "used": 0,
            "window_seconds": int(limit_item.get_expiry()),
            "resets_at": None,
        }

    try:
        stats = limiter.limiter.get_window_stats(limit_item, *identifiers)
        remaining = int(stats.remaining)
        capacity = int(limit_item.amount)
        used = max(0, capacity - remaining)
        reset_iso = datetime.fromtimestamp(stats.reset_time, tz=timezone.utc).isoformat()
    except Exception:
        remaining = int(limit_item.amount)
        capacity = int(limit_item.amount)
        used = 0
        reset_iso = None

    return {
        "limit": limit_string,
        "capacity": capacity,
        "remaining": remaining,
        "used": used,
        "window_seconds": int(limit_item.get_expiry()),
        "resets_at": reset_iso,
    }


def require_feature_access(user: dict | None, feature_key: str) -> dict:
    if user is None:
        abort(401, "User context missing.")

    plan_key, plan = resolve_plan(user.get("plan"))
    allowed_features = plan.get("features", [])

    if feature_key not in allowed_features:
        abort(403, f"Your {plan.get('label', plan_key)} plan does not include this feature.")

    return plan


def register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        plans = app.config["SUBSCRIPTION_PLANS"]
        return render_template("index.html", plans=plans)

    @app.post("/auth/register")
    def register():
        payload = request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password")
        plan_key = payload.get("plan")

        if not email or not password:
            return jsonify({"message": "Email and password are required."}), 400

        plan_key, _ = resolve_plan(plan_key)

        users = get_user_collection()
        try:
            result = users.insert_one(
                {
                    "email": email,
                    "password_hash": generate_password_hash(password),
                    "plan": plan_key,
                    "created_at": datetime.utcnow().isoformat(),
                }
            )
        except DuplicateKeyError:
            return jsonify({"message": "An account with that email already exists."}), 409

        user = users.find_one({"_id": result.inserted_id})
        return jsonify({"message": "Registration successful.", "user": serialize_user(user)}), 201

    @app.post("/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""

        user = get_user_collection().find_one({"email": email})
        if not user or not check_password_hash(user.get("password_hash", ""), password):
            return jsonify({"message": "Invalid credentials."}), 401

        access_token = create_access_token(identity=str(user["_id"]))
        return jsonify({"access_token": access_token, "user": serialize_user(user)})

    @app.post("/subscription/plan")
    @jwt_required()
    def update_plan():
        payload = request.get_json(silent=True) or {}
        requested_plan = payload.get("plan")
        plan_key, plan = resolve_plan(requested_plan)

        user = get_user_from_request()
        if not user:
            abort(401)

        get_user_collection().update_one(
            {"_id": user["_object_id"]},
            {"$set": {"plan": plan_key}},
        )

        # Refresh cached user in g
        user["plan"] = plan_key
        g.current_user = user

        refreshed_token = create_access_token(identity=user["id"])

        return (
            jsonify(
                {
                    "message": f"Plan updated to {plan.get('label', plan_key)}.",
                    "plan": {"key": plan_key, **plan},
                    "access_token": refreshed_token,
                }
            ),
            200,
        )

    @app.get("/features/alpha")
    @jwt_required()
    @limiter.limit(limit_for("alpha"))
    def feature_alpha():
        user = get_user_from_request()
        require_feature_access(user, "alpha")
        return jsonify({"feature": "alpha", "data": "Alpha insights go here."})

    @app.get("/features/beta")
    @jwt_required()
    @limiter.limit(limit_for("beta"))
    def feature_beta():
        user = get_user_from_request()
        require_feature_access(user, "beta")
        return jsonify({"feature": "beta", "data": "Beta analytics go here."})

    @app.get("/features/gamma")
    @jwt_required()
    @limiter.limit(limit_for("gamma"))
    def feature_gamma():
        user = get_user_from_request()
        require_feature_access(user, "gamma")
        return jsonify({"feature": "gamma", "data": "Gamma automation goes here."})

    @app.get("/me")
    @jwt_required()
    def me():
        user = get_user_from_request()
        if not user:
            abort(401)
        plan_key, plan = resolve_plan(user.get("plan"))
        return jsonify({
            "user": serialize_user(user),
            "plan": {"key": plan_key, **plan},
        })

    @app.get("/usage")
    @jwt_required()
    def usage_dashboard():
        user = get_user_from_request()
        if not user:
            abort(401)

        plan_key, plan = resolve_plan(user.get("plan"))
        limit_key = limiter._key_func()
        usage_payload = []
        plan_limits = plan.get("limits", {})
        plan_features = plan.get("features", [])

        for feature, endpoint in FEATURE_ENDPOINTS.items():
            allowed = feature in plan_features
            limit_string = plan_limits.get(feature)
            if allowed:
                limit_string = limit_string or current_app.config["FALLBACK_RATE_LIMIT"]

            stats = _collect_usage_snapshot(limit_key, endpoint, limit_string)
            usage_payload.append(
                {
                    "feature": feature,
                    "label": FEATURE_LABELS.get(feature, feature.title()),
                    "endpoint": endpoint,
                    "allowed": allowed,
                    **stats,
                }
            )

        plan_payload = {
            "key": plan_key,
            "label": plan.get("label"),
            "features": plan_features,
            "limits": plan_limits,
        }

        return jsonify(
            {
                "plan": plan_payload,
                "usage": usage_payload,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        wants_json = request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
        api_like_path = request.path.startswith(("/auth", "/subscription", "/features", "/me"))
        if wants_json or api_like_path:
            response = {
                "message": error.description,
                "status": error.code,
            }
            return jsonify(response), error.code
        return error


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config.get("FLASK_DEBUG", False))

