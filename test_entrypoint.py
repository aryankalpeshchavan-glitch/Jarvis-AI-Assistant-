import sys
import pytest

def test_main_app_importable():
    """
    Regression test to ensure that the FastAPI app object is exportable
    from main.py without causing circular imports or NameErrors.
    """
    try:
        from main import app
        assert app is not None
        from fastapi import FastAPI
        assert isinstance(app, FastAPI)
    except Exception as e:
        pytest.fail(f"Failed to import app from main: {e}")
