"""Robustness of the main findings to the [ASSUMED] inputs.

For each perturbation of the assumed rosters / registration time, at x3
demand: is "critical-first + SPT" still better than KTAS priority on
diversion, and does it still cost KTAS 3 waiting time?

Output: results/sensitivity.md
"""
import pandas as pd
from _common import REPS, RESULTS, md_table

from er_sim import Config, paired_diff, run_many

BASE = Config(arrival_factor=3.0)
VARIANTS = {
    "as assumed": BASE,
    "nurses -1 per shift": BASE.scaled_staff(extra_nurses=-1),
    "nurses +2 per shift": BASE.scaled_staff(extra_nurses=2),
    "physicians -1 per shift": BASE.scaled_staff(extra_doctors=-1),
    "physicians +1 per shift": BASE.scaled_staff(extra_doctors=1),
    "registration x2 slower": BASE.with_(registration_tri_h=tuple(2 * x for x in BASE.registration_tri_h)),
    "2 clerks": BASE.with_(clerks=2),
}

rows = []
for name, cfg in VARIANTS.items():
    a = run_many(cfg, REPS)
    b = run_many(cfg.with_(queue_policy="critical_spt"), REPS)
    d_div = paired_diff(a, b, "diversion_rate")
    d_k3 = paired_diff(a, b, "dtd_ktas3")
    rows.append({
        "variant": name,
        "baseline diversion": f"{a.diversion_rate.mean():.1%}",
        "nurse util.": f"{a.nurse_util.mean():.0%}",
        "physician util.": f"{a.doctor_util.mean():.0%}",
        "Δ diversion, SPT − priority (%p)": f"{100 * d_div['diff']:+.2f} ± {100 * d_div['half_width']:.2f}",
        "Δ DTD KTAS 3 (min)": f"{d_k3['diff']:+.1f} ± {d_k3['half_width']:.1f}",
    })
    print(rows[-1])

text = md_table(pd.DataFrame(rows).set_index("variant")) + f"\n\nArrival factor ×3, {REPS} paired replications.\n"
(RESULTS / "sensitivity.md").write_text(text)
print(text)
