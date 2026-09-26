from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import NOW, snapshot
from trading_universe.models import Action, GateVote, TradeDecision
from trading_universe.trade_log import TradeLog, refinement_tasks
from trading_universe.training.calibration import expected_calibration_error, reward
from trading_universe.training.data_quality import PricedNews, spot_check
from trading_universe.training.retraining import RetrainingPipeline, evaluate
from trading_universe.training.schema import GATE_QUESTIONS, Output, TrainingExample, example_from_trade


def make_log(outcomes: list[float], path=None, sector="it", event_type="earnings") -> TradeLog:
    log = TradeLog(path)
    for i, move in enumerate(outcomes):
        snap = snapshot(snapshot_id=f"s{i}", sector=sector, event_type=event_type)
        d = TradeDecision("INFY", Action.BUY, 100, 100.0, 98.0, 200.0, (GateVote("news", True),), snap, NOW + timedelta(minutes=i))
        tid = f"t{i}"
        log.record_open(tid, d, 100.0, 0.0)
        log.record_close(tid, 100.0 + move, NOW + timedelta(minutes=i, seconds=30), "test", 0.0)
    return log


def test_calibration_penalises_overconfident_wrong_more():
    confident_wrong = reward(pnl=-200, risk_amount=200, confidence=0.95, correct=False)
    humble_wrong = reward(pnl=-200, risk_amount=200, confidence=0.55, correct=False)
    assert confident_wrong < humble_wrong
    assert reward(200, 200, 0.9, True) > reward(200, 200, 0.6, True)


def test_ece_zero_when_perfectly_calibrated():
    pairs = [(0.75, True)] * 3 + [(0.75, False)]
    assert expected_calibration_error(pairs) == pytest.approx(0.0)


def test_output_must_be_an_allowed_answer():
    with pytest.raises(ValueError):
        TrainingExample({}, GATE_QUESTIONS["trade"], Output("moon", 0.9))
    with pytest.raises(ValueError):
        TrainingExample({}, GATE_QUESTIONS["trade"], Output("buy", 1.2))


def test_example_from_trade_labels_losers_as_hold():
    log = make_log([+3.0, -2.0])
    win, loss = (example_from_trade(r) for r in log.closed_trades())
    assert win.output.answer == "buy" and loss.output.answer == "hold"
    assert '"allowed_answers"' in win.prompt()


def test_trade_log_round_trips_through_jsonl(tmp_path):
    path = tmp_path / "trades.jsonl"
    make_log([1.0, -1.0], path)
    reloaded = TradeLog(path)
    assert [r.pnl for r in reloaded.closed_trades()] == [100.0, -100.0]


def test_refinement_task_scoped_to_losing_cluster():
    log = make_log([-1] * 6 + [1], sector="it", event_type="earnings")
    tasks = refinement_tasks(log)
    assert len(tasks) == 1 and (tasks[0].sector, tasks[0].event_type) == ("it", "earnings")


class ConstModel:
    def __init__(self, model_id, answer, conf=0.7):
        self.model_id, self.answer, self.conf = model_id, answer, conf

    def decide(self, ex):
        return Output(self.answer, self.conf)


class OracleModel:
    model_id = "oracle"

    def decide(self, ex):
        return Output(ex.output.answer, 0.9)


class FakeTrainer:
    def __init__(self, model):
        self.model, self.datasets = model, []

    def train(self, dataset, base):
        self.datasets.append(dataset)
        return self.model


def test_pipeline_waits_until_enough_new_trades(tmp_path):
    p = RetrainingPipeline(make_log([1, -1]), FakeTrainer(OracleModel()), tmp_path, min_new_examples=5)
    assert p.run_once().status == "waiting"


def test_pipeline_promotes_only_a_better_model(tmp_path):
    log = make_log([1, -2, 3, -1, 2, -3, 1, -1, 2, -2])
    live = ConstModel("always-buy", "buy")
    trainer = FakeTrainer(OracleModel())
    p = RetrainingPipeline(log, trainer, tmp_path, live_model=live, min_new_examples=5)
    res = p.run_once()
    assert res.status == "promoted" and p.state.live_model_id == "oracle"
    assert trainer.datasets[0].exists()
    # No new trades since the watermark -> waiting, nothing retrained.
    assert p.run_once().status == "waiting"


def test_pipeline_rejects_worse_model(tmp_path):
    log = make_log([1, -2, 3, -1, 2, -3, 1, -1, 2, -2])
    p = RetrainingPipeline(log, FakeTrainer(ConstModel("bad", "sell")), tmp_path, live_model=OracleModel(), min_new_examples=5)
    res = p.run_once()
    assert res.status == "rejected" and p.live_model.model_id == "oracle"


def test_evaluate_scores_hold_as_flat():
    log = make_log([-2])
    ex = [example_from_trade(r) for r in log.closed_trades()]
    assert evaluate(ConstModel("h", "hold"), ex).profit == 0.0
    assert evaluate(ConstModel("b", "buy"), ex).profit == -200.0


def test_spot_check_flags_bad_dataset():
    rows = [PricedNews("INFY", date(2020, 1, 1) + timedelta(days=i), 100.0 + i) for i in range(200)]
    good = spot_check(rows, lambda s, d: 100.0 + (d - date(2020, 1, 1)).days)
    bad = spot_check(rows, lambda s, d: 105.0 + (d - date(2020, 1, 1)).days)
    assert good.trusted() and good.sampled == 100
    assert not bad.trusted() and bad.mismatch_rate == 1.0
