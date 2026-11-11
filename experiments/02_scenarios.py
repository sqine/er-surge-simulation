"""Scenario table: the Simio experiment's scenarios plus the two from the
experimental plan that never made it into the Simio run.

Output: results/scenarios.csv, results/scenarios.md
"""
import pandas as pd
from _common import REPS, RESULTS, md_table

from er_sim import Config, run_many, summarize

BASE = Config()
SCENARIOS = {
    # --- scenarios present in the Simio experiment (parameter values assumed)
    "Normal": BASE,
    "FewBeds (12)": BASE.with_(beds=12),
    "FewBeds (10)": BASE.with_(beds=10),
    "HighDemand (x2)": BASE.with_(arrival_factor=2.0),
    "HighDemand (x2), no fast track": BASE.with_(arrival_factor=2.0, fast_track=False),
    "ExtremeDemand (x3)": BASE.with_(arrival_factor=3.0),
    "ExtremeDemand (x3), no fast track": BASE.with_(arrival_factor=3.0, fast_track=False),
    # --- planned in the proposal, missing from the Simio experiment
    "x2 + beds +10% (17)": BASE.with_(arrival_factor=2.0, beds=17),
    "x2 + 20% beds reserved for KTAS 1-2": BASE.with_(arrival_factor=2.0, reserved_beds=3),
}
KPIS = ["diversion_rate", "diversion_ktas12", "dtd_mean", "dtd_ktas12", "dtd_p90", "los_mean_h",
        "bed_util", "doctor_util", "nurse_util"]

rows = []
for name, cfg in SCENARIOS.items():
    s = summarize(run_many(cfg, REPS), KPIS)
    row = {"scenario": name}
    for k in KPIS:
        row[k] = s.loc[k, "mean"]
        row[k + "_hw"] = s.loc[k, "half_width"]
    rows.append(row)
    print(f"{name:40s} diversion {row['diversion_rate']:.2%}  DTD {row['dtd_mean']:.1f} min")

df = pd.DataFrame(rows).set_index("scenario")
df.to_csv(RESULTS / "scenarios.csv")


def pm(m, hw, pct=False):
    return f"{m:.1%} ± {hw:.1%}" if pct else f"{m:.1f} ± {hw:.1f}"


pretty = pd.DataFrame({
    "Diversion": [pm(r.diversion_rate, r.diversion_rate_hw, True) for r in df.itertuples()],
    "Diversion KTAS 1-2": [pm(r.diversion_ktas12, r.diversion_ktas12_hw, True) for r in df.itertuples()],
    "Door-to-doctor (min)": [pm(r.dtd_mean, r.dtd_mean_hw) for r in df.itertuples()],
    "DTD KTAS 1-2 (min)": [pm(r.dtd_ktas12, r.dtd_ktas12_hw) for r in df.itertuples()],
    "DTD p90 (min)": [pm(r.dtd_p90, r.dtd_p90_hw) for r in df.itertuples()],
    "Bed util.": [f"{r.bed_util:.0%}" for r in df.itertuples()],
    "Nurse util.": [f"{r.nurse_util:.0%}" for r in df.itertuples()],
}, index=df.index)
(RESULTS / "scenarios.md").write_text(md_table(pretty) + f"\n\nMean ± 95% CI half-width, {REPS} replications.\n")
