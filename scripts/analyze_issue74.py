"""Diagnostics for issue #74 ("most cars upshift far too late").

Replays every log in ``logs/issue logs profile`` twice: once as raw telemetry
(what the game actually did) and once through a fresh ``TCULogic`` (what the
shift logic decided and why). Run from the repo root:

    python scripts/analyze_issue74.py
"""

import json
import statistics
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("keyboard", MagicMock())

import virtual_tcu.logic.tcu as tcu_module  # noqa: E402
from virtual_tcu.config.store import ConfigStore  # noqa: E402
from virtual_tcu.logic.tcu import TCULogic  # noqa: E402
from virtual_tcu.storage.profiles import ProfileStore  # noqa: E402
from virtual_tcu.telemetry.logger import TelemetryLogger  # noqa: E402
from virtual_tcu.telemetry.parser import parse_fh6_packet  # noqa: E402
from virtual_tcu.telemetry.replay_reader import iter_replay_records  # noqa: E402

BASE = Path("logs/issue logs profile")
CFG = json.loads((BASE / "tcu_config.json").read_text())
clock = {"now": 1000.0}
tcu_module.time.time = lambda: clock["now"]

NAMES = {
    "Aditional_Pagani_Huayra_R.bin.gz": "Pagani Huayra R",
    "Ford_GT.bin.gz": "Ford GT",
    "Honda_Beat.bin.gz": "Honda Beat",
    "Honda_Civic_Si.bin.gz": "Honda Civic Si",
    "Honda_Civic_Type_R.bin.gz": "Honda Civic Type R",
    "Honda_NSX-R_GT.bin.gz": "Honda NSX-R GT",
    "Lamborghini_Essenza_SCV12.bin.gz": "Lamborghini Essenza SCV12",
    "Mazda_.55_Mazda_787B.bin.gz": "Mazda 787B",
    "Mazda_Furai.bin.gz": "Mazda Furai",
}


class RecordingOutput:
    key_up, key_down = "e", "q"

    def __init__(self):
        self.n = 0
        self.last = None

    def shift_to(self, from_gear, target_gear):
        self.n += 1
        self.last = (from_gear, target_gear)

    def is_self_press(self, key):
        return False

    def shutdown(self):
        pass


def replay(path: Path, verbose: bool):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "cfg.json").write_text(json.dumps(CFG))
    out = RecordingOutput()
    tcu = TCULogic(
        out,
        ProfileStore(path=str(tmp / "prof.json")),
        ConfigStore(path=str(tmp / "cfg.json")),
        TelemetryLogger(),
    )
    tcu.set_mode("RACE")

    t0 = None
    verified_at = None
    car_frames: dict[tuple, int] = {}
    probe = None
    upshifts = []
    per_gear: dict[int, dict] = {}

    for rel_ms, raw in iter_replay_records(path):
        td = parse_fh6_packet(raw)
        if td is None or not td.is_race_on:
            continue
        if t0 is None:
            t0 = rel_ms
            probe = td
        t = (rel_ms - t0) / 1000.0
        clock["now"] = 1000.0 + t
        car_frames[td.car_key] = car_frames.get(td.car_key, 0) + 1

        if not td.is_shifting and td.gear >= 1:
            g = per_gear.setdefault(td.gear, {"n": 0, "wot_max_rpm": 0.0, "max_kmh": 0.0})
            g["n"] += 1
            g["max_kmh"] = max(g["max_kmh"], td.speed_kmh)
            if td.throttle >= 0.9:
                g["wot_max_rpm"] = max(g["wot_max_rpm"], td.current_rpm)

        before = out.n
        tcu.process(td)
        if out.n > before and out.last[1] > out.last[0]:
            upshifts.append(
                (
                    t,
                    out.last[0],
                    out.last[1],
                    td.rpm_pct,
                    tcu._effective_upshift_pct(td, 0.03),
                    tcu._wot_upshift_fallback(td),
                    tcu._tcu_state,
                )
            )
        if verified_at is None and tcu._rev_limiter.is_verified(td.car_key):
            verified_at = t

    car = max(car_frames, key=car_frames.get)
    emax = probe.engine_max_rpm
    fuel_cut = max(g["wot_max_rpm"] for g in per_gear.values())

    pc = tcu._power_curve
    fit = pc._fits.get(car)
    pt, pp, conf = pc._peaks(car)
    saved = pc._max_r.get(car, 0.0)
    pc._max_r[car] = 1.0  # what the parabola says with the coverage gate lifted
    _, pp_ungated, _ = pc._peaks(car)
    pc._max_r[car] = saved
    limiter = tcu._rev_limiter._redline.get(car)

    # The replay is closed-loop: the recorded telemetry already contains the
    # original run's gear changes, so the commands the TCU issues here track
    # them. The *final* learned target is the uncontaminated measure of where
    # this build would shift.
    final_target = upshifts[-1][4] if upshifts else float("nan")

    row = {
        "name": NAMES.get(path.name, path.name),
        "emax": emax,
        "fuel_cut": fuel_cut,
        "limiter": limiter,
        "verified_at": verified_at,
        "max_r": saved,
        "spread": fit.x_spread if fit else 0.0,
        "conf": conf,
        "pt": pt,
        "pp": pp,
        "pp_ungated": pp_ungated,
        "n_up": len(upshifts),
        "median_shift": statistics.median(u[3] for u in upshifts) if upshifts else float("nan"),
        "final_target": final_target,
        "top_gear_cmd": max((u[2] for u in upshifts), default=0),
        "target_eq_fallback": all(abs(u[4] - u[5]) < 1e-9 for u in upshifts),
    }

    if verbose:
        print(f"\n{'=' * 96}\n{row['name']}  car_key={car}  engine_max_rpm={emax:.0f}")
        print("  gear  frames   WOT max rpm    %nominal   max km/h")
        for g in sorted(per_gear):
            s = per_gear[g]
            print(
                f"  {g:>4} {s['n']:>7} {s['wot_max_rpm']:>13.0f} "
                f"{s['wot_max_rpm'] / emax * 100:>10.1f}% {s['max_kmh']:>10.1f}"
            )
        for t, a, b, rpm, tgt, fb, state in upshifts:
            print(
                f"    {t:8.2f}s {a}->{b}  rpm={rpm * 100:5.1f}%  "
                f"target={tgt * 100:5.1f}%  fallback={fb * 100:5.1f}%  [{state}]"
            )
    return row


def main():
    verbose = "-v" in sys.argv
    rows = [replay(p, verbose) for p in sorted(BASE.glob("*.bin.gz"))]
    print(
        f"\n{'car':<26}{'nominal':>8}{'fuelcut':>9}{'  ':>2}{'learned lim':>12}"
        f"{'spread':>8}{'conf':>6}{'peakPow':>9}{'final tgt':>10}{'vs cut':>8}{'topgear':>8}"
    )
    for r in rows:
        lim = r["limiter"]
        cut_pct = r["fuel_cut"] / r["emax"]
        print(
            f"{r['name']:<26}{r['emax']:>8.0f}"
            f"{r['fuel_cut']:>7.0f}/{cut_pct * 100:>4.1f}%"
            f"{(lim or 0):>7.0f}/{(lim or 0) / r['emax'] * 100:>4.1f}%"
            f"{r['spread']:>8.3f}{r['conf']:>6.2f}"
            f"{(r['pp_ungated'] or float('nan')) * 100:>8.1f}%"
            f"{r['final_target'] * 100:>9.1f}%"
            f"{(r['final_target'] - cut_pct) * r['emax']:>7.0f}r"
            f"{r['top_gear_cmd']:>8}"
        )
    print(
        "\n'final tgt' is the effective upshift target at the last command — the replay is\n"
        "closed-loop, so the RPM at each command tracks the original run and only the target\n"
        "shows what this build would do. 'vs cut' is that target's distance from the observed\n"
        "fuel cut: negative means the shift no longer waits for the limiter."
    )


if __name__ == "__main__":
    main()
