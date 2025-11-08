# Subscription Demo

This sample application demonstrates how to protect three dummy features behind subscription tiers using Flask, MongoDB, JWT authentication, and per-plan rate limiting.

## Features

- JWT-based registration and login flows backed by MongoDB
- Subscription plans (Starter, Growth, Scale) with mapped feature access
- Per-feature rate limits powered by `Flask-Limiter`, dynamically driven by the user's plan
- Live usage dashboard that visualises remaining quota and reset times for each feature
- HTML demo page with a modal to inspect and switch plans, and buttons that exercise the protected API endpoints

## Requirements

- Python 3.11+
- Access to a MongoDB instance (local or hosted)

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Update `specs.json` with your desired secrets, MongoDB connection, and plan configuration. You can create alternate specs files and point to them with the `SPECS_PATH` environment variable when starting Flask.
4. Seed MongoDB is optional; users are created via the `/auth/register` endpoint or the demo UI.

## Running the App

```bash
set FLASK_APP=app.py
set FLASK_RUN_PORT=5000
flask run
```

On macOS/Linux use `export` instead of `set`.

Visit `http://localhost:5000` to open the demo UI.

## API Overview

- `POST /auth/register` → Create an account (`email`, `password`, `plan`)
- `POST /auth/login` → Obtain a JWT access token
- `POST /subscription/plan` → Update the current user's plan (requires JWT)
- `GET /me` → Returns user details and the resolved subscription plan
- `GET /features/{alpha|beta|gamma}` → Protected feature endpoints that enforce plan access and rate limits
- `GET /usage` → Summarise current usage, remaining calls, and reset windows for each feature in the active plan

When a plan change is made, the API returns a refreshed token so the UI keeps the session in sync with the new subscription level.

## Customising Plans

- Plans, feature access, rate limits, and secrets live in `specs.json`.
- Create separate files per environment if needed and set `SPECS_PATH` before launching the app.
- After editing `specs.json`, restart the Flask server to apply changes.

## Testing the Rate Limiter

Trigger a plan-specific limit by repeatedly calling a feature endpoint with the same token. The dashboard on the homepage will update automatically, and you can also exercise the API directly:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:5000/features/alpha
```

The response becomes `429 Too Many Requests` once the configured quota is exceeded.

## Notes

- The demo uses the in-memory storage backend for `Flask-Limiter`. For production, configure `LIMITER_STORAGE_URI` to a persistent backend such as Redis.
- Passwords are hashed with Werkzeug utilities before storage.
- The UI is intentionally simple and is meant to provide a quick way to exercise the API.

