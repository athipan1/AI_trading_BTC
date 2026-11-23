"""Regression tests for low-dependency Phase 5.7 Candidate V2 metrics."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from app.research.frozen_oos_validation import FrozenOOSValidationResearch
from app.research.realized_r_metrics import realized_r_selection_metrics


@pytest.mark.parametrize(
    ("realized", "mask", "expected"),
    [
        (
            [-1.0, 2.0, -0.5, 1.0],
            [True, True, True, False],
            {
                "available_signals": 4,
                "trade_count": 3,
                "selection_rate_pct": 75.0,
                "win_rate_pct": pytest.approx(100 / 3),
                "expectancy_r": pytest.approx(1 / 6),
                "total_realized_r": 0.5,
                "profit_factor": pytest.approx(4 / 3),
                "max_drawdown_r": 1.0,
            },
        ),
        (
            [1.0, -3.0],
            [False, False],
            {
                "available_signals": 2,
                "trade_count": 0,
                "selection_rate_pct": 0.0,
                "win_rate_pct": None,
                "expectancy_r": None,
                "total_realized_r": 0.0,
                "profit_factor": None,
                "max_drawdown_r": 0.0,
            },
        ),
        (
            [1.0, 2.0],
            [True, True],
            {
                "available_signals": 2,
                "trade_count": 2,
                "selection_rate_pct": 100.0,
                "win_rate_pct": 100.0,
                "expectancy_r": 1.5,
                "total_realized_r": 3.0,
                "profit_factor": None,
                "max_drawdown_r": 0.0,
            },
        ),
    ],
)
def test_shared_metrics_match_frozen_contract(
    realized: list[float],
    mask: list[bool],
    expected: dict[str, object],
) -> None:
    assert realized_r_selection_metrics(realized, mask) == expected
    assert FrozenOOSValidationResearch._metrics(
        np.array(realized, dtype=float), np.array(mask, dtype=bool)
    ) == expected


def test_metrics_fail_closed_on_mismatched_mask() -> None:
    with pytest.raises(ValueError, match="identical lengths"):
        realized_r_selection_metrics([1.0, -1.0], [True])


def test_candidate_import_is_independent_of_sklearn_and_numpy() -> None:
    code = """
import builtins
real_import = builtins.__import__
def block_ml(name, *args, **kwargs):
    if name == 'sklearn' or name.startswith('sklearn.') or name == 'numpy':
        raise ModuleNotFoundError('blocked for minimal Termux Candidate V2 test')
    return real_import(name, *args, **kwargs)
builtins.__import__ = block_ml
from app.research.candidate_v2_research import CandidateV2Research
assert CandidateV2Research().SCHEMA_VERSION == 'candidate_v2_discovery_study_v1'
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
