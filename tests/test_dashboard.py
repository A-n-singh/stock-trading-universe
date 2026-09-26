from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
pytest.importorskip("vectorbt")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).parents[1] / "app" / "dashboard.py")


def demo_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    at.toggle[0].set_value(True).run()  # generated prices: no network needed
    return at


def test_dashboard_loads_prices_and_tabs():
    at = demo_app()
    assert not at.exception
    assert at.title[0].value.startswith("📈")
    assert len(at.tabs) == 5
    assert any("generated" in w.value for w in at.warning)


def test_dashboard_runs_the_settings_search():
    at = demo_app()
    at.button[0].click().run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Settings tested" in labels and "Passed hidden exam" in labels
    tested = next(m for m in at.metric if m.label == "Settings tested")
    assert tested.value == "525"


def test_dashboard_switches_to_stocks():
    at = demo_app()
    at.radio[0].set_value("Stocks (Yahoo Finance)").run()
    assert not at.exception
    assert "RELIANCE.NS" in at.multiselect[0].value
