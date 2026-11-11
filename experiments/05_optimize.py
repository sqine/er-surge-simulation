"""Simulation optimization: cheapest resource plan that survives a x3 surge.

    min   daily cost(beds, extra nurses, extra doctors)
    s.t.  P(diverted)            <= 2%   (upper 95% CI bound)
          P(diverted | KTAS 1-2) <= 1%   (upper 95% CI bound)
          mean door-to-doctor, KTAS 3 <= 30 min (KTAS target; upper CI bound)
    over  beds in 15..32, +0..3 nurses and +0..1 doctors on every shift,
          queue policy in {KTAS priority, critical-first + SPT}

Two-stage search: screen every configuration with a few replications, then
re-evaluate the cheapest promising ones with many replications and accept the
first whose CI upper bounds meet both limits.

Costs are ILLUSTRATIVE assumptions (KRW/day), not hospital data.
Output: results/optimization_screen.csv, results/optimization_confirm.csv, results/optimization.md
"""
import itertools
import os
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
from _common import RESULTS, md_table

from er_sim import Config
from er_sim.experiment import _job, t_halfwidth

FACTOR = 3.0
DIV_MAX, DIV12_MAX, DTD3_MAX = 0.02, 0.01, 30.0
COST_BED_DAY = 250_000            # [ASSUMED] staffed bed operating cost
COST_NURSE_HOUR = 40_000          # [ASSUMED]
COST_DOCTOR_HOUR = 150_000        # [ASSUMED]
SCREEN_REPS, CONFIRM_REPS, SHORTLIST = 8, 50, 8  # shortlist per policy

BASE = Config(arrival_factor=FACTOR)
POLICIES = {"KTAS priority": "severity", "Critical-first + SPT": "critical_spt"}


def daily_cost(beds, extra_nurses, extra_doctors):
    return (beds * COST_BED_DAY + extra_nurses * 24 * COST_NURSE_HOUR
            + extra_doctors * 24 * COST_DOCTOR_HOUR)


def evaluate(configs, reps, seed0):
    jobs = [(cfg, seed0 + r) for _, cfg in configs for r in range(reps)]
    with ProcessPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(_job, jobs, chunksize=8))
    out = []
    for i, (key, _) in enumerate(configs):
        df = pd.DataFrame(res[i * reps:(i + 1) * reps])
        row = dict(key)
        for k in ("diversion_rate", "diversion_ktas12", "dtd_ktas12", "dtd_ktas3", "nurse_util"):
            row[k] = df[k].mean()
            row[k + "_ub"] = df[k].mean() + t_halfwidth(df[k])
        out.append(row)
    return pd.DataFrame(out)


grid = []
for beds, en, ed, (pname, pol) in itertools.product(range(15, 33), range(4), range(2), POLICIES.items()):
    key = {"policy": pname, "beds": beds, "extra_nurses": en, "extra_doctors": ed,
           "cost_krw_day": daily_cost(beds, en, ed)}
    grid.append((key, BASE.with_(beds=beds, queue_policy=pol).scaled_staff(ed, en)))

screen = evaluate(grid, SCREEN_REPS, seed0=50_000).sort_values("cost_krw_day")
screen.to_csv(RESULTS / "optimization_screen.csv", index=False)
print(f"screened {len(grid)} configurations")

# shortlist: cheapest configurations whose screening means already meet the limits
def meets(df, sfx=""):
    return ((df["diversion_rate" + sfx] <= DIV_MAX) & (df["diversion_ktas12" + sfx] <= DIV12_MAX)
            & (df["dtd_ktas3" + sfx] <= DTD3_MAX))


ok = screen[meets(screen)]
short = ok.groupby("policy").head(SHORTLIST)
lookup = {tuple(k.values()): cfg for k, cfg in grid}
cand = [(dict(r[["policy", "beds", "extra_nurses", "extra_doctors", "cost_krw_day"]]),
         lookup[(r.policy, r.beds, r.extra_nurses, r.extra_doctors, r.cost_krw_day)])
        for _, r in short.iterrows()]
confirm = evaluate(cand, CONFIRM_REPS, seed0=90_000).sort_values("cost_krw_day")
confirm["feasible"] = meets(confirm, "_ub")
confirm.to_csv(RESULTS / "optimization_confirm.csv", index=False)

# best plan per policy, plus the cheapest "beds only" plan for comparison
best = confirm[confirm.feasible].groupby("policy").head(1)
beds_only = screen[(screen.extra_nurses == 0) & (screen.extra_doctors == 0)
                   & (screen.policy == "KTAS priority")]
beds_only_ok = beds_only[meets(beds_only)]

cols = ["policy", "beds", "extra_nurses", "extra_doctors", "cost_krw_day",
        "diversion_rate", "diversion_rate_ub", "diversion_ktas12", "diversion_ktas12_ub",
        "dtd_ktas12", "dtd_ktas3", "nurse_util"]
table = best[cols].copy()
for c in ("diversion_rate", "diversion_rate_ub", "diversion_ktas12", "diversion_ktas12_ub", "nurse_util"):
    table[c] = table[c].map(lambda v: f"{v:.2%}")
for c in ("dtd_ktas12", "dtd_ktas3"):
    table[c] = table[c].map(lambda v: f"{v:.1f}")
table["cost_krw_day"] = table["cost_krw_day"].map(lambda v: f"₩{v:,.0f}")

note = (f"Surge ×{FACTOR:g}. Feasible = 95% CI upper bound of diversion ≤ {DIV_MAX:.0%} and of "
        f"KTAS 1-2 diversion ≤ {DIV12_MAX:.0%} and of KTAS 3 door-to-doctor ≤ {DTD3_MAX:.0f} min, "
        f"{CONFIRM_REPS} replications. "
        f"Screened {len(grid)} configurations × {SCREEN_REPS} reps.\n")
if len(beds_only_ok):
    b = beds_only_ok.iloc[0]
    note += (f"\nBeds-only plan (KTAS priority, no extra staff) needs {int(b.beds)} beds "
             f"(₩{b.cost_krw_day:,.0f}/day, screening estimate).\n")
else:
    note += "\nNo beds-only plan (≤ 32 beds, no extra staff) meets the limits.\n"
text = md_table(table.set_index("policy")) + "\n\n" + note
(RESULTS / "optimization.md").write_text(text)
print(text)
