import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_LAT = 1.349383588
SRC_LON = 103.6877553
SGT = timezone(timedelta(hours=8))
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "sample_nea_lightning_data.json"


def offset_from_center(radius_km, angle_rad):
    delta_lat = (radius_km / 111.0) * math.cos(angle_rad)
    cos_lat = max(0.2, math.cos(math.radians(SRC_LAT)))
    delta_lon = (radius_km / (111.0 * cos_lat)) * math.sin(angle_rad)
    return SRC_LAT + delta_lat, SRC_LON + delta_lon


def to_iso_with_ms(dt):
    return dt.isoformat(timespec="milliseconds")


def build_readings(record_time, close_count, mid_count, far_count, rng):
    readings = []

    for _ in range(close_count):
        radius = rng.uniform(1.0, 14.5)
        angle = rng.uniform(0, 2 * math.pi)
        lat, lon = offset_from_center(radius, angle)
        event_time = record_time - timedelta(seconds=rng.randint(0, 110))
        readings.append(
            {
                "location": {
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                },
                "type": "C",
                "text": "Cloud to Cloud",
                "datetime": to_iso_with_ms(event_time),
            }
        )

    for _ in range(mid_count):
        radius = rng.uniform(15.3, 29.7)
        angle = rng.uniform(0, 2 * math.pi)
        lat, lon = offset_from_center(radius, angle)
        event_time = record_time - timedelta(seconds=rng.randint(0, 110))
        readings.append(
            {
                "location": {
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                },
                "type": "C",
                "text": "Cloud to Cloud",
                "datetime": to_iso_with_ms(event_time),
            }
        )

    for _ in range(far_count):
        radius = rng.uniform(31.0, 42.0)
        angle = rng.uniform(0, 2 * math.pi)
        lat, lon = offset_from_center(radius, angle)
        event_time = record_time - timedelta(seconds=rng.randint(0, 110))
        readings.append(
            {
                "location": {
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                },
                "type": "C",
                "text": "Cloud to Cloud",
                "datetime": to_iso_with_ms(event_time),
            }
        )

    return readings


def build_records(now_sgt, interval_minutes, seed):
    rng = random.Random(seed)
    step_count = int((24 * 60) / interval_minutes) + 1
    records = []

    for step in range(step_count):
        record_time = (now_sgt - timedelta(minutes=step * interval_minutes)).replace(
            second=0, microsecond=0
        )

        # Keep a visible, non-flat trend across 24 hours.
        close_base = 4 + 3 * math.sin(step / 4.3)
        mid_base = 5 + 4 * math.cos(step / 6.2)
        far_base = 1 + max(0, math.sin(step / 7.5))

        close_count = max(0, int(round(close_base + rng.uniform(-1.2, 2.4))))
        mid_count = max(0, int(round(mid_base + rng.uniform(-1.0, 2.8))))
        far_count = max(0, int(round(far_base + rng.uniform(-0.4, 1.4))))

        readings = build_readings(record_time, close_count, mid_count, far_count, rng)
        records.append(
            {
                "datetime": record_time.isoformat(),
                "item": {
                    "isStationData": False,
                    "readings": readings,
                    "type": "observation",
                },
                "updatedTimestamp": (record_time + timedelta(minutes=2)).isoformat(),
            }
        )

    return records


def main():
    parser = argparse.ArgumentParser(
        description="Generate sample lightning data covering the latest 24 hours."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path (default: tests/sample_nea_lightning_data.json).",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=2,
        help="Record interval in minutes (default: 2).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed (default: derived from current date).",
    )
    args = parser.parse_args()

    now_sgt = datetime.now(SGT)
    seed = args.seed if args.seed is not None else int(now_sgt.strftime("%Y%m%d"))

    records = build_records(now_sgt, max(1, args.interval_minutes), seed)
    payload = {
        "code": 0,
        "data": {"records": records},
        "errorMsg": "",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {len(records)} records into: {args.output}")
    print(f"Now(SGT): {now_sgt.isoformat(timespec='seconds')}")
    print(f"Seed: {seed}")


if __name__ == "__main__":
    main()
