"""Discrete-event model of an emergency department (SimPy).

Flow: arrival (NHPP) -> registration (KTAS 1 fast-tracked) -> bed
(no bed -> diverted) -> physician -> nursing care -> release bed -> disposition.
Physicians and nurses serve by KTAS priority (or FCFS) and follow 3-hour
rosters. A patient keeps the bed from allocation until nursing care ends.

Common random numbers: arrivals come from one stream, and every patient draws
exactly five uniforms from a second stream in arrival order, so two
configurations with the same arrival process see identical patients.
"""
from __future__ import annotations

import math

import numpy as np
import simpy

from .params import BLOCK_HOURS, DISPOSITIONS, Config

PATIENT_PRIORITY_FCFS = 0
# "critical_spt": KTAS 1-2 first, then KTAS 3-5 by shortest expected
# physician + nursing time (KTAS 5 < 4 < 3) - an SPT rule borrowed from
# single-machine scheduling, applied only below the critical tier.
CRITICAL_SPT_PRIORITY = {1: 1, 2: 2, 5: 3, 4: 4, 3: 5}
BLOCKER_PRIORITY = -1  # off-duty "blockers" outrank every patient


def tri_inv(u: float, a: float, c: float, b: float) -> float:
    """Inverse CDF of Triangular(min=a, mode=c, max=b)."""
    fc = (c - a) / (b - a)
    if u < fc:
        return a + math.sqrt(u * (b - a) * (c - a))
    return b - math.sqrt((1 - u) * (b - a) * (b - c))


def categorical(u: float, probs) -> int:
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if u < acc:
            return i
    return len(probs) - 1


class TimeWeighted:
    """Time-average of a piecewise-constant level, restricted to [start, end]."""

    def __init__(self, env: simpy.Environment, start: float, end: float):
        self.env, self.start, self.end = env, start, end
        self.level, self.last, self.area = 0, 0.0, 0.0

    def _accrue(self, now: float):
        lo, hi = max(self.last, self.start), min(now, self.end)
        if hi > lo:
            self.area += self.level * (hi - lo)
        self.last = now

    def add(self, delta: int):
        self._accrue(self.env.now)
        self.level += delta

    def mean(self) -> float:
        self._accrue(self.env.now)
        return self.area / (self.end - self.start)


class RosteredStaff:
    """PriorityResource whose on-duty capacity follows a 3-hour roster.

    Off-duty units are held by top-priority blocker requests. Blockers never
    preempt: a staff member going off duty finishes the current patient first.
    """

    def __init__(self, env, roster, start, end):
        self.env, self.roster = env, roster
        self.res = simpy.PriorityResource(env, capacity=max(roster))
        self.blockers: list = []
        self.busy = TimeWeighted(env, start, end)
        self.on_duty = TimeWeighted(env, start, end)
        env.process(self._shift_changes())

    def _shift_changes(self):
        block = 0
        while True:
            target_off = self.res.capacity - self.roster[block % len(self.roster)]
            while len(self.blockers) < target_off:
                self.blockers.append(self.res.request(priority=BLOCKER_PRIORITY))
            while len(self.blockers) > target_off:
                req = self.blockers.pop()
                if req.triggered:
                    self.res.release(req)
                else:
                    req.cancel()
            self.on_duty.add(self.roster[block % len(self.roster)] - self.on_duty.level)
            block += 1
            yield self.env.timeout(BLOCK_HOURS)

    def utilization(self) -> float:
        duty = self.on_duty.mean()
        return self.busy.mean() / duty if duty > 0 else float("nan")


class EmergencyDepartment:
    def __init__(self, cfg: Config, seed: int):
        self.cfg = cfg
        ss = np.random.SeedSequence(seed)
        arr_ss, pat_ss = ss.spawn(2)
        self.rng_arrival = np.random.default_rng(arr_ss)
        self.rng_patient = np.random.default_rng(pat_ss)

        self.env = env = simpy.Environment()
        self.t0 = cfg.warmup_h
        self.t1 = cfg.warmup_h + cfg.horizon_h

        self.clerks = simpy.Resource(env, capacity=cfg.clerks)
        self.doctors = RosteredStaff(env, cfg.doctor_roster, self.t0, self.t1)
        self.nurses = RosteredStaff(env, cfg.nurse_roster, self.t0, self.t1)
        self.beds_in_use = 0
        self.bed_level = TimeWeighted(env, self.t0, self.t1)

        self.records: list[dict] = []
        self.trace: list[tuple[float, int]] = []
        env.process(self._arrivals())
        if cfg.trace:
            env.process(self._sample_beds())

    # ---------------------------------------------------------------- arrivals
    def _rate(self, t: float) -> float:
        prof = self.cfg.rate_profile
        return prof[int(t // BLOCK_HOURS) % len(prof)] * self.cfg.arrival_factor

    def _arrivals(self):
        lam_max = max(self.cfg.rate_profile) * self.cfg.arrival_factor
        pid = 0
        while True:
            yield self.env.timeout(self.rng_arrival.exponential(1 / lam_max))
            if self.env.now >= self.t1:
                return  # stop arrivals; remaining patients drain
            if self.rng_arrival.random() < self._rate(self.env.now) / lam_max:
                u = self.rng_patient.random(5)
                self.env.process(self._patient(pid, u))
                pid += 1

    def _sample_beds(self):
        while True:
            self.trace.append((self.env.now, self.beds_in_use))
            yield self.env.timeout(1.0)

    # ----------------------------------------------------------------- patient
    def _bed_available(self, ktas: int) -> bool:
        cfg = self.cfg
        if cfg.beds is None:
            return True
        limit = cfg.beds if ktas <= 2 else cfg.beds - cfg.reserved_beds
        return self.beds_in_use < limit

    def _priority(self, ktas: int) -> int:
        policy = self.cfg.queue_policy
        if policy == "severity":
            return ktas
        if policy == "critical_spt":
            return CRITICAL_SPT_PRIORITY[ktas]
        if policy == "fcfs":
            return PATIENT_PRIORITY_FCFS
        raise ValueError(f"unknown queue_policy {policy!r}")

    def _patient(self, pid: int, u):
        cfg, env = self.cfg, self.env
        ktas = categorical(u[0], cfg.ktas_probs) + 1
        rec = {"pid": pid, "ktas": ktas, "t_arrive": env.now}
        if self.t0 <= env.now < self.t1:
            self.records.append(rec)  # filled in as the patient progresses

        if cfg.use_registration and not (cfg.fast_track and ktas == 1):
            with self.clerks.request() as req:
                yield req
                yield env.timeout(tri_inv(u[1], *cfg.registration_tri_h))

        if not self._bed_available(ktas):
            rec["diverted"] = True
            return
        rec["diverted"] = False
        self.beds_in_use += 1
        self.bed_level.add(+1)

        # physician
        req = self.doctors.res.request(priority=self._priority(ktas))
        yield req
        rec["t_doctor"] = env.now
        self.doctors.busy.add(+1)
        if cfg.exp_doctor_mean_h is not None:
            dt = -cfg.exp_doctor_mean_h * math.log(1 - u[2])
        else:
            dt = tri_inv(u[2], *cfg.doctor_tri_h[ktas - 1])
        yield env.timeout(dt)
        self.doctors.res.release(req)
        self.doctors.busy.add(-1)

        # nursing care
        if cfg.use_nurse:
            req = self.nurses.res.request(priority=self._priority(ktas))
            yield req
            rec["t_nurse"] = env.now
            self.nurses.busy.add(+1)
            yield env.timeout(tri_inv(u[3], *cfg.nurse_tri_h[ktas - 1]))
            self.nurses.res.release(req)
            self.nurses.busy.add(-1)

        self.beds_in_use -= 1
        self.bed_level.add(-1)
        rec["t_leave"] = env.now
        rec["disposition"] = DISPOSITIONS[categorical(u[4], cfg.disposition_probs[ktas - 1])]

    # --------------------------------------------------------------------- run
    def run(self) -> "EmergencyDepartment":
        self.env.run(until=self.t1 + self.cfg.drain_h)
        return self


def kpis(ed: EmergencyDepartment) -> dict:
    """Per-replication KPIs (times in minutes)."""
    recs = ed.records
    n = len(recs)
    recs = [r for r in recs if "diverted" in r]  # reached the bed decision
    n = len(recs)
    served = [r for r in recs if not r["diverted"] and "t_leave" in r]
    dtd = np.array([(r["t_doctor"] - r["t_arrive"]) * 60 for r in served])
    los = np.array([(r["t_leave"] - r["t_arrive"]) for r in served])
    hi = np.array([r["ktas"] <= 2 for r in served], dtype=bool)
    k3 = np.array([r["ktas"] == 3 for r in served], dtype=bool)
    cfg = ed.cfg
    bed_cap = cfg.beds if cfg.beds is not None else float("nan")
    out = {
        "arrivals": n,
        "diversion_rate": sum(r["diverted"] for r in recs) / n if n else float("nan"),
        "diversion_ktas12": (np.mean([r["diverted"] for r in recs if r["ktas"] <= 2])
                             if any(r["ktas"] <= 2 for r in recs) else float("nan")),
        "dtd_mean": dtd.mean() if dtd.size else float("nan"),
        "dtd_p90": np.percentile(dtd, 90) if dtd.size else float("nan"),
        "dtd_ktas12": dtd[hi].mean() if hi.any() else float("nan"),
        "dtd_ktas345": dtd[~hi].mean() if (~hi).any() else float("nan"),
        "dtd_ktas3": dtd[k3].mean() if k3.any() else float("nan"),
        "los_mean_h": los.mean() if los.size else float("nan"),
        "over24h_rate": (los > 24).mean() if los.size else float("nan"),
        "bed_util": ed.bed_level.mean() / bed_cap,
        "doctor_util": ed.doctors.utilization(),
        "nurse_util": ed.nurses.utilization(),
        "unfinished": len(ed.records) - len(served) - sum(r["diverted"] for r in recs),
    }
    return out
