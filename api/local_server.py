"""Local ASGI entry point: uvicorn local_server:create_local_app --factory."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.app_factory import create_app


def create_local_app() -> FastAPI:
    load_dotenv(Path(__file__).with_name(".env"))
    return create_app("local")
