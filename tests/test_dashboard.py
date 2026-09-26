from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
pytest.importorskip("vectorbt")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).parents[1] / "app" / "dashboard.py")


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("TU_RUNS_DIR", str(tmp_path / "runs"))


def button(at: AppTest, text: str):
    return next(b for b in at.button if text in b.label)


def demo_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    at.toggle(key="demo").set_value(True).run()  # generated prices: no network needed
    return at


def test_dashboard_loads_prices_and_tabs():
    at = demo_app()
    assert not at.exception
    assert at.title[0].value.startswith("📈")
    assert len(at.tabs) == 7
    assert any("generated" in w.value for w in at.warning)


def test_dashboard_runs_the_settings_search():
    at = demo_app()
    button(at, "Run settings search").click().run()
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


def test_live_tab_shows_empty_state_before_any_run():
    at = demo_app()
    assert any("hasn't run yet" in i.value for i in at.info)
