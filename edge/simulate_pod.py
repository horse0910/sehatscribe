"""Simulate the Arduino UNO Q vitals pod from any computer.

Usage:
    SEHAT_DEVICE_TOKEN=demo-token sehatscribe serve --host 0.0.0.0
    python edge/simulate_pod.py --url http://127.0.0.1:8000 --token demo-token
"""

import argparse
import json
import random
import time
import urllib.request


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--token", required=True)
    p.add_argument("--once", action="store_true", help="Send one reading and exit")
    args = p.parse_args()

    while True:
        reading = {
            "device_id": "uno-q-sim",
            "bp_systolic": random.randint(112, 132),
            "bp_diastolic": random.randint(72, 86),
            "temperature_f": round(random.uniform(99.5, 101.8), 1),
            "spo2": random.randint(95, 99),
            "pulse": random.randint(78, 102),
        }
        req = urllib.request.Request(
            f"{args.url}/api/devices/vitals",
            data=json.dumps(reading).encode(),
            headers={"Content-Type": "application/json", "X-Device-Token": args.token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(resp.status, reading)
        if args.once:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
