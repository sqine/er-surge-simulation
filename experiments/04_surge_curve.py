"""Sweep the arrival factor to find where the ED tips over.

Output: results/surge_curve.csv, results/surge_diversion.png
"""
import numpy as np
import pandas as pd
from _common import REPS, RESULTS, SERIES, plt, save

from er_sim import Config, run_many, summarize

FACTORS = np.round(np.arange(1.0, 4.01, 0.25), 2)
POLICIES = {
    "KTAS priority (baseline)": dict(),
    "Critical-first + SPT": dict(queue_policy="critical_spt"),
    "Reserve 3 beds for KTAS 1-2": dict(reserved_beds=3),
}
KPIS = ["diversion_rate", "diversion_ktas12", "dtd_ktas12", "dtd_mean"]

rows = []
for name, kw in POLICIES.items():
    for f in FACTORS:
        s = summarize(run_many(Config(arrival_factor=float(f), **kw), REPS), KPIS)
        rows.append({"policy": name, "arrival_factor": f,
                     **{k: s.loc[k, "mean"] for k in KPIS},
                     **{k + "_hw": s.loc[k, "half_width"] for k in KPIS}})
    print(name, "done")
df = pd.DataFrame(rows)
df.to_csv(RESULTS / "surge_curve.csv", index=False)


def panel(ax, col, scale, ylabel, title):
    for color, (name, g) in zip(SERIES, df.groupby("policy", sort=False)):
        m, hw = g[col] * scale, g[col + "_hw"] * scale
        ax.fill_between(g.arrival_factor, m - hw, m + hw, color=color, alpha=0.15, linewidth=0)
        ax.plot(g.arrival_factor, m, color=color, label=name)
    ax.set_xlabel("Arrival rate multiplier (× Seoul ED baseline)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontsize=10)
    ax.legend(loc="upper left")


fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
panel(axes[0], "diversion_rate", 100, "Diverted patients (%)", "All patients diverted")
panel(axes[1], "diversion_ktas12", 100, "Diverted KTAS 1-2 patients (%)", "Critical patients diverted")
save(fig, "surge_diversion.png")

base = df[df.policy == "KTAS priority (baseline)"]
knee = base[base.diversion_rate > 0.05].arrival_factor.min()
print(f"baseline crosses 5% diversion at x{knee}")
