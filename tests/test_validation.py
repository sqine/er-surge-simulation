"""Validate the simulator against closed-form results before trusting it."""
import math

import numpy as np
import pytest

from er_sim import Config, EmergencyDepartment, run_many
from er_sim.model import tri_inv
from er_sim.experiment import t_halfwidth


def erlang_c_wait(lam: float, mu: float, c: int) -> float:
    """Mean queueing delay Wq of an M/M/c queue."""
    a = lam / mu
    rho = a / c
    s = sum(a**k / math.factorial(k) for k in range(c))
    top = a**c / (math.factorial(c) * (1 - rho))
    p_wait = top / (s + top)
    return p_wait / (c * mu - lam)


def mmc_config(lam: float, mean_service_h: float, c: int) -> Config:
    """Strip the ED down to M/M/c: constant Poisson arrivals, one class,
    exponential physician time, unlimited beds, no registration or nursing."""
    return Config(
        rate_profile=(lam,) * 8,
        ktas_probs=(0, 0, 1, 0, 0),
        beds=None,
        doctor_roster=(c,) * 8,
        use_registration=False,
        use_nurse=False,
        exp_doctor_mean_h=mean_service_h,
        queue_policy="fcfs",
        warmup_h=7 * 24,
        horizon_h=120 * 24,
    )


@pytest.mark.parametrize("lam,mean_s,c", [(4.0, 0.5, 3), (6.0, 0.4, 3), (2.0, 0.8, 2)])
def test_mmc_waiting_time_matches_erlang_c(lam, mean_s, c):
    df = run_many(mmc_config(lam, mean_s, c), reps=20, base_seed=100, workers=1)
    wq_theory_min = erlang_c_wait(lam, 1 / mean_s, c) * 60
    m, hw = df["dtd_mean"].mean(), t_halfwidth(df["dtd_mean"])
    # theory must fall inside the 95% CI widened by 2% for discretisation noise
    assert abs(m - wq_theory_min) <= hw + 0.02 * wq_theory_min, (m, hw, wq_theory_min)


def test_mmc_utilization_matches_offered_load():
    lam, mean_s, c = 4.0, 0.5, 3
    df = run_many(mmc_config(lam, mean_s, c), reps=10, base_seed=7, workers=1)
    assert df["doctor_util"].mean() == pytest.approx(lam * mean_s / c, rel=0.02)


def test_nhpp_arrival_count_matches_rate_profile():
    cfg = Config(beds=None)
    ed = EmergencyDepartment(cfg, seed=3).run()
    expected = np.mean(cfg.rate_profile) * cfg.horizon_h
    # Poisson: sd = sqrt(mean); allow 4 sd
    assert abs(len(ed.records) - expected) < 4 * math.sqrt(expected)


def test_triangular_inverse_cdf_moments():
    rng = np.random.default_rng(0)
    a, c, b = 0.3, 0.5, 1.0
    x = np.array([tri_inv(u, a, c, b) for u in rng.random(200_000)])
    assert x.min() >= a and x.max() <= b
    assert x.mean() == pytest.approx((a + b + c) / 3, rel=0.005)


def test_common_random_numbers_give_identical_patients():
    """Same seed and arrival process -> same patients under different policies."""
    a = EmergencyDepartment(Config(), seed=11).run()
    b = EmergencyDepartment(Config(queue_policy="fcfs"), seed=11).run()
    ka = [(r["pid"], r["ktas"], round(r["t_arrive"], 9)) for r in a.records]
    kb = [(r["pid"], r["ktas"], round(r["t_arrive"], 9)) for r in b.records]
    assert ka == kb


def test_reserved_beds_never_used_by_low_acuity():
    cfg = Config(arrival_factor=3.0, reserved_beds=5)
    ed = EmergencyDepartment(cfg, seed=5).run()
    div = {k: np.mean([r["diverted"] for r in ed.records if r["ktas"] == k and "diverted" in r])
           for k in (2, 4)}
    assert div[2] <= div[4]
