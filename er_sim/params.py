"""Model inputs.

Values marked [DATA] come from the team's Simio model documentation, which was
fitted to e+MEDIS Seoul emergency-department statistics (2016-2024).
Values marked [ASSUMED] were not recoverable from the documentation and are
explicit, documented assumptions; change them here and every experiment picks
them up.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

BLOCK_HOURS = 3.0  # rate table and staff rosters are piecewise constant per 3h

# [DATA] patients/hour for 00-03, 03-06, ..., 21-24 (Simio RateTable)
RATE_PROFILE = (1.00, 0.65, 0.86, 1.74, 1.65, 1.68, 1.77, 1.40)

# [DATA] KTAS 1..5 share of arrivals
KTAS_PROBS = (0.011, 0.063, 0.400, 0.415, 0.111)

# [DATA] physician examination time, Triangular(min, mode, max) in hours
DOCTOR_TRI_H = (
    (1.0, 1.5, 2.5),
    (0.5, 0.8, 1.5),
    (0.3, 0.5, 1.0),
    (0.2, 0.3, 0.5),
    (0.1, 0.2, 0.3),
)

# [DATA] nursing care time, Triangular(min, mode, max) in hours
NURSE_TRI_H = (
    (4.0, 6.0, 9.0),
    (3.0, 4.0, 6.0),
    (1.5, 2.5, 4.0),
    (0.5, 1.0, 2.0),
    (0.2, 0.4, 0.7),
)

# [DATA] disposition probabilities by KTAS
DISPOSITIONS = ("ICU", "Ward", "Morgue", "Exit")
DISPOSITION_PROBS = (
    (0.60, 0.20, 0.15, 0.05),
    (0.20, 0.50, 0.20, 0.10),
    (0.05, 0.40, 0.10, 0.45),
    (0.05, 0.10, 0.05, 0.80),
    (0.01, 0.02, 0.00, 0.97),
)

# [DATA] 5,918 ED beds / 409 EDs in Seoul = 14.5 -> 15 beds
BEDS = 15

# [ASSUMED] on-duty staff per 3h block. Sized from e+MEDIS averages
# (6.8 EM specialists, 35.1 nurses per ED) and the documented "fewer staff in
# low-demand hours" roster; exact Simio work schedules were not recoverable.
DOCTOR_ROSTER = (2, 2, 2, 3, 3, 3, 3, 2)
NURSE_ROSTER = (6, 6, 7, 9, 9, 9, 9, 8)

# [ASSUMED] registration desk: 1 clerk, Triangular(3, 5, 10) minutes
CLERKS = 1
REGISTRATION_TRI_H = (3 / 60, 5 / 60, 10 / 60)


@dataclass(frozen=True)
class Config:
    # demand
    arrival_factor: float = 1.0
    rate_profile: tuple = RATE_PROFILE
    ktas_probs: tuple = KTAS_PROBS
    # resources
    beds: int | None = BEDS            # None = unlimited
    reserved_beds: int = 0             # beds only KTAS 1-2 may occupy
    doctor_roster: tuple = DOCTOR_ROSTER
    nurse_roster: tuple = NURSE_ROSTER
    clerks: int = CLERKS
    # process
    fast_track: bool = True            # KTAS 1 skips registration
    queue_policy: str = "severity"     # "severity" | "fcfs" | "critical_spt"
    use_registration: bool = True
    use_nurse: bool = True
    registration_tri_h: tuple = REGISTRATION_TRI_H
    doctor_tri_h: tuple = DOCTOR_TRI_H
    nurse_tri_h: tuple = NURSE_TRI_H
    disposition_probs: tuple = DISPOSITION_PROBS
    # validation hook: if set, physician time ~ Exponential(mean) for all KTAS
    exp_doctor_mean_h: float | None = None
    # run control (hours)
    warmup_h: float = 3 * 24
    horizon_h: float = 30 * 24         # measured window after warm-up
    drain_h: float = 3 * 24            # arrivals stop; let measured patients finish
    trace: bool = False                # record hourly bed occupancy

    def with_(self, **kw) -> "Config":
        return replace(self, **kw)

    def scaled_staff(self, extra_doctors: int = 0, extra_nurses: int = 0) -> "Config":
        return replace(
            self,
            doctor_roster=tuple(d + extra_doctors for d in self.doctor_roster),
            nurse_roster=tuple(n + extra_nurses for n in self.nurse_roster),
        )
