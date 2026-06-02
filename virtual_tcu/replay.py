"""Format Virtual TCU replay logs (.bin / .bin.gz) to readable text."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path
from typing import IO, TextIO

from virtual_tcu.telemetry.model import Telemetry
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records


def analyze_shift_latency(paths: list[Path], out: TextIO) -> None:
    import statistics

    from virtual_tcu.config.store import ConfigStore
    from virtual_tcu.input.interface import OutputInterface
    from virtual_tcu.logic.tcu import TCULogic
    from virtual_tcu.storage.profiles import ProfileStore
    from virtual_tcu.telemetry.logger import TelemetryLogger

    class MockOutput(OutputInterface):
        def __init__(self, clock: MockClock):
            self._clock = clock
            self.last_shift_time: float | None = None

        @property
        def key_up(self) -> str: return "e"

        @property
        def key_down(self) -> str: return "q"

        def is_self_press(self, key: str) -> bool: return False

        def shift_to(self, from_gear: int, target_gear: int):
            # Record time in the same clock domain as rel_ms/clock.now.
            self.last_shift_time = self._clock.now

        def shutdown(self): pass

    class MockClock:
        def __init__(self):
            self.now = 0.0
        def __call__(self):
            return self.now

    if not paths:
        return

    out.write("\n=== Shift Latency A/B Analysis ===\n")
    for path in paths:
        cfg = ConfigStore(path="dummy.json")
        prof = ProfileStore(path="dummy.json")
        clock = MockClock()
        mock_out = MockOutput(clock)
        tcu = TCULogic(mock_out, prof, cfg, TelemetryLogger())

        import virtual_tcu.logic.tcu
        original_time = virtual_tcu.logic.tcu.time.time
        virtual_tcu.logic.tcu.time.time = clock
        latencies = []
        pending_shift_time = None
        prev_gear = None

        try:
            for rel_ms, raw in iter_replay_records(path):
                t = parse_fh6_packet(raw)
                if t is None:
                    continue
                clock.now = rel_ms / 1000.0
                
                # Check for gear change
                if prev_gear is not None and t.gear != prev_gear and pending_shift_time is not None:
                    latencies.append((clock.now - pending_shift_time) * 1000.0)
                    pending_shift_time = None

                mock_out.last_shift_time = None
                tcu.process(t)
                
                if mock_out.last_shift_time is not None:
                    pending_shift_time = mock_out.last_shift_time

                prev_gear = t.gear

            if latencies:
                latencies.sort()
                median = statistics.median(latencies)
                p90 = latencies[int(len(latencies) * 0.90)]
                p99 = latencies[int(len(latencies) * 0.99)]
                out.write(f"{path.name}:\n")
                out.write(f"  Samples: {len(latencies)}\n")
                out.write(f"  Median : {median:.1f} ms\n")
                out.write(f"  P90    : {p90:.1f} ms\n")
                out.write(f"  P99    : {p99:.1f} ms\n")
            else:
                out.write(f"{path.name}:\n  No shifts detected.\n")
        finally:
            virtual_tcu.logic.tcu.time.time = original_time

    out.write("==================================\n\n")

def _gear_label(gear: int) -> str:
    if gear == 0:
        return "R"
    if gear == 11:
        return "N"
    if gear > 11:
        return f"S{gear - 11}"
    return str(gear)


def format_text_line(rel_ms: int, t: Telemetry, *, prev_gear: int | None) -> str:
    shift = ""
    if prev_gear is not None and t.gear != prev_gear:
        shift = f"  << {_gear_label(prev_gear)}->{_gear_label(t.gear)}"
    return (
        f"{rel_ms:7d} ms  "
        f"gear={_gear_label(t.gear):>2}  "
        f"rpm={t.current_rpm:6.0f}/{t.engine_max_rpm:.0f}  "
        f"speed={t.speed_kmh:6.1f} km/h  "
        f"T={t.throttle:.2f} B={t.brake:.2f}  "
        f"pwr={t.power_w / 1000:5.1f} kW  "
        f"trq={t.torque_nm:5.0f} Nm  "
        f"race={'Y' if t.is_race_on else 'N'}"
        f"{shift}"
    )


def telemetry_record(rel_ms: int, t: Telemetry) -> dict[str, object]:
    """All parsed FH6 Car Dash fields (raw + derived) for inspection."""
    record = {f.name: getattr(t, f.name) for f in fields(Telemetry)}
    record.update(
        {
            "time_ms": rel_ms,
            "gear_label": _gear_label(t.gear),
            "speed_kmh": round(t.speed_kmh, 4),
            "speed_effective_ms": round(t.speed_effective_ms, 4),
            "rpm_pct": round(t.rpm_pct, 6),
            "throttle": round(t.throttle, 6),
            "brake": round(t.brake, 6),
            "clutch": round(t.clutch_raw / 255.0, 6),
            "power_kw": round(t.power_w / 1000, 4),
            "drivetrain_name": t.drivetrain_name,
            "rear_slip": round(t.rear_slip, 4),
            "front_slip": round(t.front_slip, 4),
        }
    )
    return record


def format_csv_row(rel_ms: int, t: Telemetry) -> dict[str, object]:
    return telemetry_record(rel_ms, t)


def format_replay(
    path: Path,
    out: TextIO,
    *,
    fmt: str,
    shift_only: bool,
) -> dict:
    prev_gear: int | None = None
    parsed = 0
    skipped = 0
    shifts = 0
    first_ms: int | None = None
    last_ms: int | None = None
    car_ordinal: int | None = None
    tune_keys: set[tuple[int, int, int]] = set()
    csv_rows: list[dict] = []
    json_rows: list[dict] = []

    if fmt == "text":
        out.write(f"# file: {path.name}\n")

    for rel_ms, raw in iter_replay_records(path):
        if first_ms is None:
            first_ms = rel_ms
        last_ms = rel_ms
        t = parse_fh6_packet(raw)
        if t is None:
            skipped += 1
            continue
        if car_ordinal is None and t.car_ordinal:
            car_ordinal = t.car_ordinal
        if t.is_race_on and t.car_ordinal:
            tune_keys.add((t.car_ordinal, t.pi, int(t.engine_max_rpm)))

        gear_changed = prev_gear is not None and t.gear != prev_gear
        if gear_changed:
            shifts += 1
        include = not shift_only or gear_changed or prev_gear is None

        if fmt == "text" and include:
            out.write(format_text_line(rel_ms, t, prev_gear=prev_gear) + "\n")
        elif fmt == "json" and include:
            json_rows.append(telemetry_record(rel_ms, t))
        elif fmt == "jsonl" and include:
            out.write(json.dumps(telemetry_record(rel_ms, t), ensure_ascii=False) + "\n")
        elif fmt == "csv" and include:
            csv_rows.append(format_csv_row(rel_ms, t))

        prev_gear = t.gear
        parsed += 1

    if fmt == "csv" and csv_rows:
        writer = csv.DictWriter(out, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)
    elif fmt == "summary":
        duration_s = ((last_ms or 0) - (first_ms or 0)) / 1000.0
        out.write(f"{path.name}\n")
        out.write(f"  packets: {parsed} parsed, {skipped} skipped\n")
        out.write(f"  duration: {duration_s:.2f} s\n")
        out.write(f"  gear changes: {shifts}\n")
        if car_ordinal is not None:
            out.write(f"  car_ordinal: {car_ordinal}\n")
        if tune_keys:
            out.write("  tune variants (car_ordinal, pi, max_rpm):\n")
            for key in sorted(tune_keys):
                out.write(f"    - {key}\n")
        out.write("\n")

    duration_ms = (last_ms - first_ms) if first_ms is not None and last_ms is not None else 0
    return {
        "path": path,
        "parsed": parsed,
        "skipped": skipped,
        "shifts": shifts,
        "duration_ms": duration_ms,
        "car_ordinal": car_ordinal,
        "json_rows": json_rows,
    }


def format_paths(
    paths: Iterable[Path],
    out: TextIO,
    *,
    fmt: str,
    shift_only: bool,
) -> None:
    path_list = list(paths)
    if not path_list:
        raise SystemExit("no input files matched")

    totals = {"parsed": 0, "skipped": 0, "shifts": 0}
    json_rows: list[dict] = []
    for i, path in enumerate(path_list):
        stats = format_replay(path, out, fmt=fmt, shift_only=shift_only)
        totals["parsed"] += stats["parsed"]
        totals["skipped"] += stats["skipped"]
        totals["shifts"] += stats["shifts"]
        if fmt == "json":
            rows = stats["json_rows"]
            if len(path_list) > 1:
                for row in rows:
                    row["_source_file"] = path.name
            json_rows.extend(rows)

        if fmt == "text" and len(path_list) > 1 and i < len(path_list) - 1:
            out.write("\n")

    if fmt == "json" and json_rows:
        json.dump(json_rows, out, ensure_ascii=False, indent=2)
        out.write("\n")

    if len(path_list) > 1 and fmt == "text":
        out.write(
            f"\n# total: {totals['parsed']} packets, "
            f"{totals['skipped']} skipped, {totals['shifts']} gear changes\n"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Format Virtual TCU replay logs (.bin / .bin.gz) to readable output.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="replay log file(s), e.g. logs/tcu_replay_*.bin.gz",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write to file instead of stdout",
    )
    parser.add_argument(
        "--format",
        choices=("text", "csv", "json", "jsonl", "summary"),
        default="text",
        help="output format: json = single JSON array; jsonl = one object per line",
    )
    parser.add_argument(
        "--shift-only",
        action="store_true",
        help="only print rows where gear changed",
    )
    parser.add_argument(
        "--clutch-ab",
        action="store_true",
        help="analyze shift latency (time from command to actual gear change)",
    )
    return parser


def resolve_paths(patterns: Iterable[Path]) -> list[Path] | None:
    paths: list[Path] = []
    for pattern in patterns:
        if any(ch in str(pattern) for ch in "*?[]"):
            paths.extend(sorted(Path().glob(str(pattern))))
        elif pattern.exists():
            paths.append(pattern)
        else:
            print(f"[replay] file not found: {pattern}", file=sys.stderr)
            return None
    return paths


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = resolve_paths(args.files)
    if paths is None:
        return 1

    out_io: IO[str]
    close_out = False
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        out_io = args.output.open("w", encoding="utf-8", newline="")
        close_out = True
    else:
        out_io = sys.stdout

    try:
        if args.clutch_ab:
            analyze_shift_latency(paths, out_io)
        else:
            format_paths(paths, out_io, fmt=args.format, shift_only=args.shift_only)
    except ValueError as e:
        print(f"[replay] {e}", file=sys.stderr)
        return 1
    finally:
        if close_out:
            out_io.close()
            print(f"[replay] wrote {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
