from pymongo import MongoClient
from flask import current_app, g


CLIENT_KEY = "mongo_client"


def get_client() -> MongoClient:
    client = getattr(g, CLIENT_KEY, None)
    if client is None:
        client = MongoClient(current_app.config["MONGO_URI"])
        setattr(g, CLIENT_KEY, client)
    return client


def get_db():
    client = get_client()
    return client[current_app.config["MONGO_DB_NAME"]]


def close_client(error=None):  # noqa: ARG001 - Flask teardown signature requires the argument
    client = getattr(g, CLIENT_KEY, None)
    if client is not None:
        client.close()
        delattr(g, CLIENT_KEY)

