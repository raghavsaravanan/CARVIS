"""Shared test setup.

``main`` captures ``CARVIS_DEFAULT_SHOP_ID`` at import (M2 A4), and the fixtures' Qdrant data uses
the local default shop. Pin it before any test module imports ``main`` so a developer's shell or
``backend/.env`` cannot change which shop the suite reads. Tests that exercise configuration set
and clear it themselves with monkeypatch or a fresh interpreter.
"""
import os

os.environ["CARVIS_DEFAULT_SHOP_ID"] = "shop_demo"
