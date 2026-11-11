"""Justify the warm-up length (Welch's method) and the replication count.

Outputs: results/warmup_welch.png, results/replications.csv
"""
import numpy as np
import pandas as pd
from _common import REPS, SERIES, INK2, RESULTS, plt, save

from er_sim import Config, EmergencyDepartment
from er_sim.experiment import run_many, t_halfwidth

FACTOR = 2.0  # surge level: the regime where warm-up bias matters most

# ---- Welch: hourly bed occupancy averaged over replications, from empty start
n_rep, hours = 30, 10 * 24
traces = []
for r in range(n_rep):
    cfg = Config(arrival_factor=FACTOR, warmup_h=0, horizon_h=hours, drain_h=0, trace=True)
    ed = EmergencyDepartment(cfg, seed=r).run()
    traces.append([b for _, b in ed.trace[:hours]])
mean_curve = np.mean(traces, axis=0)
window = 24  # moving average over one day removes the daily cycle
ma = pd.Series(mean_curve).rolling(window, center=True).mean()

fig, ax = plt.subplots(figsize=(7, 3.2))
ax.plot(np.arange(hours) / 24, mean_curve, color=SERIES[0], linewidth=1, alpha=0.35,
        label="Hourly mean over 30 reps")
ax.plot(np.arange(hours) / 24, ma, color=SERIES[0], label="24h moving average")
ax.axvline(3, color=INK2, linewidth=1, linestyle="--")
ax.text(3.08, 0.3, "warm-up cut (3 days)", color=INK2, va="bottom", fontsize=9)
ax.set_xlabel("Day")
ax.set_ylabel("Beds occupied")
ax.set_title(f"Welch plot, arrival factor {FACTOR:g} - steady state within the first day",
             loc="left", fontsize=10)
ax.legend(loc="lower right")
save(fig, "warmup_welch.png")

# ---- replication count: CI half-width vs n
rows = []
for factor in (1.0, 2.0, 3.0):
    df = run_many(Config(arrival_factor=factor), reps=100, base_seed=10_000)
    for n in (10, 20, 30, 50, 100):
        sub = df.iloc[:n]
        rows.append({
            "arrival_factor": factor, "n": n,
            "dtd_mean": sub.dtd_mean.mean(), "dtd_hw": t_halfwidth(sub.dtd_mean),
            "dtd_rel_hw": t_halfwidth(sub.dtd_mean) / sub.dtd_mean.mean(),
            "diversion": sub.diversion_rate.mean(), "diversion_hw": t_halfwidth(sub.diversion_rate),
        })
out = pd.DataFrame(rows)
out.to_csv(RESULTS / "replications.csv", index=False)
print(out.round(4).to_string(index=False))
print(f"\nREPS used in experiments: {REPS}")
