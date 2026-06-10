import httpx
from fastapi import Request

from app.shared.store import Store, slack_token_store, token_store


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client.get()


def get_oauth_state_store(request: Request) -> Store:
    return request.app.state.oauth_state_store


def get_token_store() -> Store:
    return token_store.get()


def get_slack_token_store() -> Store:
    return slack_token_store.get()


def get_client_registry(request: Request) -> Store:
    return request.app.state.client_registry
