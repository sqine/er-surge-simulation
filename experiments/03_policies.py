"""Paired policy comparison with common random numbers.

Each alternative is compared with the baseline (KTAS-priority queues, fast
track on, no reserved beds) on the same seeds; the CI is on the
per-replication difference.

Output: results/policies.csv, results/policies.md
"""
import pandas as pd
from _common import REPS, RESULTS, md_table

from er_sim import Config, paired_diff, run_many

KPIS = ["diversion_rate", "diversion_ktas12", "dtd_ktas12", "dtd_ktas3", "dtd_ktas345", "dtd_p90"]
ALTERNATIVES = {
    "FCFS queues": dict(queue_policy="fcfs"),
    "Critical-first + SPT": dict(queue_policy="critical_spt"),
    "No fast track": dict(fast_track=False),
    "Reserve 3 beds for KTAS 1-2": dict(reserved_beds=3),
    "Beds +2 (17)": dict(beds=17),
}

rows = []
for factor in (2.0, 3.0):
    base_cfg = Config(arrival_factor=factor)
    base = run_many(base_cfg, REPS)
    for name, kw in ALTERNATIVES.items():
        alt = run_many(base_cfg.with_(**kw), REPS)
        for k in KPIS:
            d = paired_diff(base, alt, k)
            rows.append({"arrival_factor": factor, "alternative": name, **d})

df = pd.DataFrame(rows)
df.to_csv(RESULTS / "policies.csv", index=False)

UNITS = {"diversion_rate": "%p", "diversion_ktas12": "%p", "dtd_ktas12": "min", "dtd_ktas3": "min",
         "dtd_ktas345": "min", "dtd_p90": "min"}


def fmt(r):
    scale = 100 if UNITS[r.kpi] == "%p" else 1
    star = "" if r.significant else " (n.s.)"
    return f"{r['diff'] * scale:+.2f} ± {r.half_width * scale:.2f}{star}"


blocks = []
for factor, g in df.groupby("arrival_factor"):
    t = g.assign(cell=g.apply(fmt, axis=1)).pivot(index="alternative", columns="kpi", values="cell")
    t = t[KPIS].rename(columns={k: f"Δ {k} ({UNITS[k]})" for k in KPIS})
    blocks.append(f"### Arrival factor ×{factor:g}\n\n" + md_table(t))
text = "\n\n".join(blocks) + (
    f"\n\nDifference vs. baseline (alternative − baseline), mean ± 95% CI half-width "
    f"over {REPS} paired replications. n.s. = CI contains 0.\n")
(RESULTS / "policies.md").write_text(text)
print(text)
