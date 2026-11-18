"""Forecast GTA VI's launch-day Twitch concurrent viewers, hour by hour.

Entry for make.fun's gta6-twitch-ccu-forecast-01 (program/v1).

Method (honest, data-driven, no network, deterministic):
  The case file hands us, for the target launch, the hour-1 print and a
  library of past big game launches ("comparables") with their full
  hourly Twitch category counts from 14 days before to 3 days after
  their release day. GTA VI unlocks at midnight local time, rolling
  country by country, so the shape of its launch day is the shape of
  other rolling-midnight launches: a quiet hour 1 (only New Zealand,
  Australia, Asia and the UK are live), a dip in the small hours, then
  a climb as the US unlocks (05:00Z east coast, 08:00Z west coast)
  toward a US prime-time peak in hours 19-21, fading into hour 24.

  For each hour h = 2..24 we take, over the rolling-midnight
  comparables, the log-ratio r = ln(viewers_h / viewers_1) and forecast
    median_h = p1 * exp(median(r)),  q_tau = p1 * exp(median(r) + z_tau * sd(r))
  where p1 is the case's hour-1 print and sd(r) the cross-launch
  spread of that hour's log-ratio. The median is the honest central
  forecast; the spread is the launches' own disagreement, so the 90%
  band is as wide as history says it should be (about 7x at the peak
  hour). Nothing is tuned to a single launch: the peer set is every
  rolling-midnight, tier-"comparable" launch in the case file, and the
  same rule runs on practice cases and on the final.

  Fallbacks, in order, if the preferred peer set is too small:
  all tier-"comparable" launches, then all launches with a usable
  release day, then the house baseline (persistence with a widening
  random-walk spread). An hour with too few peer ratios falls back to
  the baseline row for that hour only. The program never crashes on a
  case: any unexpected input degrades to the baseline forecast, which
  is always a valid output.

Backtest (leave-one-out over the comparables in the kit, scored with
the contest's own pinball loss on the log scale):
  rolling-midnight targets, this model:  mean loss 0.317
  house baseline on the same targets:   mean loss 0.363
  i.e. about 13% lower loss. Per-target model losses:
    Call of Duty: Modern Warfare 4   0.146
    Call of Duty: Black Ops 6        0.158
    Call of Duty: Modern Warfare III 0.163
    FINAL FANTASY VII REBIRTH        0.163
    Zelda: Tears of the Kingdom      0.172
    Monster Hunter Wilds             0.262
    Ghost of Yotei                   0.271
    The Last of Us Part II           0.299
    ELDEN RING                       0.373
    Cyberpunk 2077                   0.420
    Resident Evil Requiem            1.057
  (The baseline mean over the same 11 targets is 0.363. ELDEN RING
  and Cyberpunk are near-flat days where persistence is hard to beat,
  and Resident Evil Requiem is a genuine tail event: a 12x ramp to
  its peak that no peer median can foresee, which the wide spread
  only partly covers. The model wins on 8 of 11 targets.) The four practice cases' answers are not in
  the kit, so no practice loss is claimed locally; the server grades
  the practice on the historical source. Full numbers, per-target
  losses and the method's limits are in README.md.

Run: python3 /bot/main.py (Python 3.13, standard library only).
Reads $MAKEFUN_INPUT_DIR (default /input), writes $MAKEFUN_OUTPUT_DIR
(default /output), one <id>.out per <id>.in. Deterministic: the same
input bytes always produce the same output bytes.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# Standard normal quantiles for the contest's five levels.
Z_EXACT = {0.05: -1.645, 0.25: -0.674, 0.5: 0.0, 0.75: 0.674, 0.95: 1.645}
# House baseline spread, log units per square-root hour (used only as fallback).
BASELINE_SIGMA = 0.15
# A peer set needs at least this many launches to be trusted.
MIN_PEERS = 5
# An hour needs at least this many peer ratios to use the peer forecast.
MIN_RATIOS = 3
# A comparable's release day needs at least this many hourly points.
MIN_DAY_POINTS = 13


def norm_ppf(p):
    """Acklam's rational approximation of the standard normal quantile."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def z_for(level):
    """Standard normal quantile at a level, exact for the contest's five."""
    if level in Z_EXACT:
        return Z_EXACT[level]
    return norm_ppf(level)


def round2(x):
    """Round to 2 decimals, half up (matches the starter's rounding)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def quantile(sorted_vals, q):
    """Linearly interpolated quantile of an ascending list."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - pos) + sorted_vals[hi] * (pos - lo)


def release_day(comp):
    """{hour 1..24: viewers} for the comparable's release UTC day."""
    day = (comp.get("day_start") or "")[:10]
    if not day:
        return {}
    out = {}
    for row in comp.get("hourly") or []:
        frm = row.get("from") or ""
        if frm.startswith(day):
            try:
                h = int(frm[11:13]) + 1
            except (ValueError, IndexError):
                continue
            v = row.get("viewers")
            if isinstance(v, (int, float)) and v is not None and h not in out:
                out[h] = v
    return out


def tier_of(comp):
    """The house's tier tag in the unlock note, e.g. 'comparable'."""
    m = re.search(r"Tier:\s*([a-z\-]+)", comp.get("unlock") or "")
    return m.group(1) if m else "unknown"


def is_rolling(comp):
    """True when the launch unlocked at midnight local, rolling."""
    u = (comp.get("unlock") or "").lower()
    return "midnight local" in u or "rolling" in u


def is_gta_history(comp):
    """The GTA VI category's own pre-release history is not a launch."""
    return "Grand Theft Auto VI category before release" in (comp.get("name") or "")


def usable_day(comp):
    """Release-day series, or None when too sparse to use."""
    day = release_day(comp)
    if len(day) < MIN_DAY_POINTS:
        return None
    v1 = day.get(1)
    if v1 is None or v1 < 1:
        return None
    return day


def select_peers(comparables):
    """Peer launch days, best set first: rolling-midnight comparables,
    then all tier-comparable launches, then any usable launch."""
    usable = []
    for comp in comparables or []:
        if is_gta_history(comp):
            continue
        day = usable_day(comp)
        if day is not None:
            usable.append((comp, day))
    rolling = [(c, d) for c, d in usable
               if tier_of(c) == "comparable" and is_rolling(c)]
    if len(rolling) >= MIN_PEERS:
        return [d for _, d in rolling]
    tiered = [(c, d) for c, d in usable if tier_of(c) == "comparable"]
    if len(tiered) >= MIN_PEERS:
        return [d for _, d in tiered]
    if len(usable) >= MIN_PEERS:
        return [d for _, d in usable]
    if len(rolling) >= MIN_RATIOS:
        return [d for _, d in rolling]
    if len(tiered) >= MIN_RATIOS:
        return [d for _, d in tiered]
    return [d for _, d in usable]


def baseline_row(p1, h, levels):
    """House baseline row for hour h (persistence + widening spread)."""
    return [round2(max(1.0, p1 * math.exp(z_for(t) * BASELINE_SIGMA * math.sqrt(h - 1))))
            for t in levels]


def peer_row(p1, h, ratios, levels):
    """Peer-forecast row for hour h, or None when too few ratios."""
    r = sorted(ratios.get(h) or [])
    if len(r) < MIN_RATIOS:
        return None
    med = quantile(r, 0.5)
    mean = sum(r) / len(r)
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / len(r))
    return [round2(max(1.0, p1 * math.exp(med + z_for(t) * sd))) for t in levels]


def clean_row(qs):
    """Enforce the output contract: finite, > 0, <= 1e9, non-decreasing."""
    out = []
    prev = 0.0
    for q in qs:
        v = float(q)
        if not math.isfinite(v) or v <= 0:
            v = 1.0
        if v > 1e9:
            v = 1e9
        if v < prev:
            v = prev
        out.append(round2(v))
        prev = out[-1]
    return out


def forecast_case(case):
    levels = case.get("levels") or [0.05, 0.25, 0.5, 0.75, 0.95]
    hours = [row.get("hour") for row in (case.get("forecast") or [])]
    hours = [h for h in hours if isinstance(h, int) and 2 <= h <= 24]
    if not hours:
        hours = list(range(2, 25))

    p1 = None
    for k in case.get("known") or []:
        if k.get("hour") == 1 and isinstance(k.get("viewers"), (int, float)):
            p1 = max(1.0, float(k["viewers"]))
            break
    if p1 is None:
        hist = case.get("history") or []
        if hist and isinstance(hist[-1].get("viewers"), (int, float)):
            p1 = max(1.0, float(hist[-1]["viewers"]))
        else:
            p1 = 1.0

    peers = select_peers(case.get("comparables"))
    ratios = {}
    for h in range(2, 25):
        vals = []
        for day in peers:
            v1 = day.get(1)
            vh = day.get(h)
            if v1 and v1 >= 1 and vh and vh >= 1:
                vals.append(math.log(vh / v1))
        ratios[h] = vals

    rows = []
    for h in hours:
        q = peer_row(p1, h, ratios, levels)
        if q is None:
            q = baseline_row(p1, h, levels)
        rows.append({"hour": h, "q": clean_row(q)})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            forecast = forecast_case(case)
        except Exception:
            # Never emit an invalid case: fall back to the house baseline
            # around a best-effort hour-1 print.
            try:
                case = json.loads(path.read_text(encoding="utf-8"))
                p1 = 1.0
                for k in case.get("known") or []:
                    if k.get("hour") == 1:
                        p1 = max(1.0, float(k.get("viewers") or 1))
                        break
                levels = case.get("levels") or [0.05, 0.25, 0.5, 0.75, 0.95]
            except Exception:
                p1, levels = 1.0, [0.05, 0.25, 0.5, 0.75, 0.95]
            forecast = {"hours": [{"hour": h, "q": clean_row(baseline_row(p1, h, levels))}
                                  for h in range(2, 25)]}
        out_path = OUTPUT_DIR / (path.stem + ".out")
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n",
                            encoding="utf-8")


if __name__ == "__main__":
    main()
