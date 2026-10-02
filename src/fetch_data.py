"""
ดึงข้อมูล OpenAQ สำหรับสถานีที่เลือกไว้ตาม Day 1 checklist:
- ใกล้นิคม: Health Promotion Hospital Maptaput, Field Crop Research Center
- พื้นหลัง: Pluakdaeng District Health Office
เซฟข้อมูลรายชั่วโมงดิบ (ไม่ทำความสะอาด) ไว้ที่ data/raw/openaq_hourly_raw.csv
"""

import os
import sys
import time
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

API_BASE = "https://api.openaq.org/v3"
API_KEY = os.getenv("OPENAQ_API_KEY")

# พิกัดศูนย์กลางนิคมอุตสาหกรรมมาบตาพุด, ระยอง
MAPTAPHUT_COORDINATES = "12.6833,101.1333"
RADIUS_METERS = 25000  # ค่าสูงสุดที่ OpenAQ v3 อนุญาต

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def _headers() -> dict:
    if not API_KEY:
        raise RuntimeError(
            "ไม่พบ OPENAQ_API_KEY ใน .env กรุณาสร้างไฟล์ .env แล้วใส่ key ก่อนรันสคริปต์นี้"
        )
    return {"X-API-Key": API_KEY}


def get_nearby_locations() -> list[dict]:
    """หาสถานีตรวจวัดในรัศมี RADIUS_METERS รอบมาบตาพุด"""
    resp = requests.get(
        f"{API_BASE}/locations",
        headers=_headers(),
        params={
            "coordinates": MAPTAPHUT_COORDINATES,
            "radius": RADIUS_METERS,
            "limit": 100,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["results"]


def get_location_sensors(location_id: int) -> list[dict]:
    """เช็กแต่ละพารามิเตอร์ของสถานีนี้ พร้อมช่วงเวลาที่มีข้อมูลจริง"""
    resp = requests.get(
        f"{API_BASE}/locations/{location_id}/sensors",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["results"]


# สถานีที่เลือกไว้ตาม Day 1 checklist (role: near = ใกล้นิคม, background = พื้นหลัง)
STATIONS = {
    225611: {
        "name": "Health Promotion Hospital Maptaput",
        "role": "near",
        "sensors": {
            "so2": 1304138,
            "pm25": 1305053,
            "pm10": 1304102,
            "co": 1304170,
            "no2": 1304096,
            "o3": 1304419,
        },
    },
    7846: {
        "name": "Field Crop Research Center, Rayong",
        "role": "near",
        "sensors": {
            "so2": 22766,
            "pm25": 1611423,
            "pm10": 22767,
            "co": 22763,
            "no2": 22764,
            "o3": 22765,
        },
    },
    717: {
        "name": "Pluakdaeng District Health Office",
        "role": "background",
        "sensors": {
            "so2": 1243,
            "pm25": 1304268,
            "pm10": 1266,
            "no2": 1268,
            "o3": 1267,
        },
    },
}

def _get_hours_page(sensor_id: int, datetime_from: str, datetime_to: str, page: int, limit: int = 1000) -> list[dict]:
    for attempt in range(6):
        try:
            resp = requests.get(
                f"{API_BASE}/sensors/{sensor_id}/hours",
                headers=_headers(),
                params={
                    "datetime_from": datetime_from,
                    "datetime_to": datetime_to,
                    "limit": limit,
                    "page": page,
                },
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            print(f"    [retry] connection error: {e}")
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code in (408, 429, 500, 502, 503):
            time.sleep(3 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()["results"]
    resp.raise_for_status()
    return []


def fetch_sensor_hours(sensor_id: int, year_from: int = 2016) -> list[dict]:
    """ดึงค่ารายชั่วโมงทั้งหมดของ sensor นี้ แบ่งดึงเป็นช่วงปี เพื่อเลี่ยง timeout ตอน offset ลึก"""
    import datetime as dt

    results = []
    limit = 1000
    this_year = dt.datetime.now(dt.timezone.utc).year
    for year in range(year_from, this_year + 1):
        chunk_from = f"{year}-01-01T00:00:00Z"
        chunk_to = f"{year + 1}-01-01T00:00:00Z"
        page = 1
        while True:
            batch = _get_hours_page(sensor_id, chunk_from, chunk_to, page, limit)
            results.extend(batch)
            if len(batch) < limit:
                break
            page += 1
            time.sleep(0.3)
        time.sleep(0.3)
    return results


CHECKPOINT_DIR = RAW_DIR / "hourly_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    import pandas as pd

    for station_id, meta in STATIONS.items():
        print(f"=== {meta['name']} (id={station_id}, role={meta['role']}) ===")
        for param, sensor_id in meta["sensors"].items():
            ckpt_path = CHECKPOINT_DIR / f"{station_id}_{param}.csv"
            if ckpt_path.exists():
                print(f"  - {param}: ข้ามแล้ว (มี checkpoint อยู่แล้ว)")
                continue

            hours = fetch_sensor_hours(sensor_id)
            print(f"  - {param}: {len(hours)} ชั่วโมง")

            rows = [
                {
                    "station_id": station_id,
                    "station_name": meta["name"],
                    "role": meta["role"],
                    "parameter": param,
                    "datetime_utc": h["period"]["datetimeFrom"]["utc"],
                    "datetime_local": h["period"]["datetimeFrom"]["local"],
                    "value": h["value"],
                    "units": h["parameter"]["units"],
                    "percent_coverage": h["coverage"]["percentCoverage"],
                }
                for h in hours
            ]
            pd.DataFrame(rows).to_csv(ckpt_path, index=False, encoding="utf-8-sig")

    all_dfs = [pd.read_csv(p) for p in sorted(CHECKPOINT_DIR.glob("*.csv"))]
    df = pd.concat(all_dfs, ignore_index=True)
    out_path = RAW_DIR / "openaq_hourly_raw.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nบันทึกข้อมูลรายชั่วโมงดิบ {len(df)} แถว ไว้ที่ {out_path}")


if __name__ == "__main__":
    main()
