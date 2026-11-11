"""Replication runner and output analysis.

Replication r of every configuration uses seed ``base_seed + r``; together
with the per-patient random numbers in model.py this gives common random
numbers, so differences between configurations are estimated with paired
(per-replication) differences rather than two independent samples.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from scipy import stats

from .model import EmergencyDepartment, kpis
from .params import Config


def run_replication(cfg: Config, seed: int) -> dict:
    ed = EmergencyDepartment(cfg, seed).run()
    return {"rep": seed, **kpis(ed)}


def _job(args):
    cfg, seed = args
    return run_replication(cfg, seed)


def run_many(cfg: Config, reps: int, base_seed: int = 0, workers: int | None = None) -> pd.DataFrame:
    jobs = [(cfg, base_seed + r) for r in range(reps)]
    workers = workers or min(os.cpu_count() or 1, reps)
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            rows = list(ex.map(_job, jobs))
    else:
        rows = [_job(j) for j in jobs]
    return pd.DataFrame(rows)


def t_halfwidth(x, alpha: float = 0.05) -> float:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if x.size < 2:
        return float("nan")
    return stats.t.ppf(1 - alpha / 2, x.size - 1) * x.std(ddof=1) / np.sqrt(x.size)


def summarize(df: pd.DataFrame, cols=None, alpha: float = 0.05) -> pd.DataFrame:
    cols = cols or [c for c in df.columns if c != "rep"]
    rows = []
    for c in cols:
        m, hw = df[c].mean(), t_halfwidth(df[c], alpha)
        rows.append({"kpi": c, "mean": m, "half_width": hw, "lo": m - hw, "hi": m + hw})
    return pd.DataFrame(rows).set_index("kpi")


def paired_diff(a: pd.DataFrame, b: pd.DataFrame, col: str, alpha: float = 0.05) -> dict:
    """CI for E[b - a] from replications paired by seed."""
    m = a[["rep", col]].merge(b[["rep", col]], on="rep", suffixes=("_a", "_b"))
    d = (m[f"{col}_b"] - m[f"{col}_a"]).to_numpy()
    hw = t_halfwidth(d, alpha)
    return {"kpi": col, "diff": d.mean(), "half_width": hw,
            "lo": d.mean() - hw, "hi": d.mean() + hw,
            "significant": not (d.mean() - hw <= 0 <= d.mean() + hw)}
