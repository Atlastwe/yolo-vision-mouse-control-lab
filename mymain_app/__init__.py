"""Modular runtime for the mymainproject entry point."""

from .app import Application
from .config import AppConfig

__all__ = ["AppConfig", "Application"]
