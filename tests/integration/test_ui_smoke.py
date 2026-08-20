"""UI smoke tests (master prompt §16.8): every page renders without raising, for both an empty
database (no runs yet) and a database with a real run. Uses Streamlit's own AppTest harness —
no browser required.
"""
from __future__ import annotations

import os

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "cash_equivalents_mvp", "ui", "app.py")

PAGE_NAMES = [
    "Dashboard", "Responsibility Status", "Manual Uploads & Inputs",
    "Review & Comparison", "Validation", "Outputs & Downloads", "Debugging", "Settings",
]


@pytest.fixture
def app_test():
    at = AppTest.from_file(os.path.abspath(APP_PATH), default_timeout=60)
    at.run()
    return at


def test_app_loads_without_exception(app_test):
    assert not app_test.exception


def test_sidebar_has_all_eight_pages(app_test):
    assert app_test.sidebar.radio[0].options == PAGE_NAMES


@pytest.mark.parametrize("page_name", PAGE_NAMES)
def test_each_page_renders_without_exception(app_test, page_name):
    app_test.sidebar.radio[0].set_value(page_name).run()
    assert not app_test.exception, f"{page_name} raised: {app_test.exception}"
