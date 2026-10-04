"""
ดึงข้อมูลลมและอากาศจาก Open-Meteo Historical API สำหรับสถานีเดียวกับ fetch_data.py

ใช้ 2 โมเดล:
- ecmwf_ifs (grid 9 กม.)  = ตัวหลัก แยกสถานีใกล้นิคมทั้งสองได้จริง แต่มีข้อมูลตั้งแต่ ~2021
- era5     (grid 25 กม.) = ตัวสำรองไว้ทำ sensitivity check ย้อนหลังได้ถึง 2016 แต่หยาบกว่า
  (สองสถานีใกล้นิคมจะตกใน grid cell เดียวกัน ได้ค่าลมเหมือนกัน — เป็นข้อจำกัดที่รู้อยู่แล้ว)

ไม่ต้องใช้ API key เซฟผลไว้ที่ data/raw/wind_hourly_raw.csv
"""

import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# พิกัดจริงของแต่ละสถานี (ดึงมาจาก OpenAQ /v3/locations)
STATIONS = {
    225611: {"lat": 12.7087, "lon": 101.1660, "name": "Health Promotion Hospital Maptaput", "role": "near"},
    7846: {"lat": 12.7352, "lon": 101.1356, "name": "Field Crop Research Center, Rayong", "role": "near"},
    717: {"lat": 12.9738, "lon": 101.2129, "name": "Pluakdaeng District Health Office", "role": "control"},
    225690: {"lat": 12.67155, "lon": 101.2758667, "name": "Agricultural Office", "role": "background_alt"},
}

MODELS = ["ecmwf_ifs", "era5"]

# ตัวแปรที่เช็กแล้วว่ามีข้อมูลจริงทั้งสองโมเดล
# หมายเหตุ: boundary_layer_height ตัดออก เพราะ API คืนค่าแค่ 7 ชม.แรกของวันแล้วเป็น None
#           และค่าที่ได้ (20-50 ม.) ต่ำผิดปกติจนไม่น่าเชื่อถือ
HOURLY_VARS = [
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
]

YEAR_FROM, YEAR_TO = 2016, 2026

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CHECKPOINT_DIR = RAW_DIR / "wind_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_year(lat: float, lon: float, model: str, year: int, max_date: str) -> dict:
    """ดึงข้อมูลรายชั่วโมง 1 ปีของ 1 จุด 1 โมเดล (retry ถ้าเน็ตหลุดหรือเซิร์ฟเวอร์ติด)

    max_date กันไม่ให้ขอวันที่เลยวันที่คลังข้อมูลมี (API จะตอบ 400)
    """
    end_date = min(f"{year}-12-31", max_date)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{year}-01-01",
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARS),
        "models": model,
        "timezone": "UTC",  # ขอเป็น UTC เพื่อให้ merge กับ datetime_utc ของข้อมูลอากาศได้ตรง
    }
    for attempt in range(6):
        try:
            resp = requests.get(API_URL, params=params, timeout=120)
        except requests.exceptions.RequestException as e:
            print(f"    [retry] connection error: {e}")
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code in (408, 429, 500, 502, 503):
            print(f"    [retry] HTTP {resp.status_code}")
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()["hourly"]
    resp.raise_for_status()
    return {}


def main():
    import pandas as pd

    today = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
    today_year = pd.Timestamp.now("UTC").year

    for model in MODELS:
        for sid, meta in STATIONS.items():
            ckpt = CHECKPOINT_DIR / f"{model}_{sid}.csv"
            if ckpt.exists():
                print(f"{model} / {sid}: ข้ามแล้ว (มี checkpoint)")
                continue

            print(f"=== {model} / {sid} {meta['name']} ===")
            frames = []
            for year in range(YEAR_FROM, min(YEAR_TO, today_year) + 1):
                hourly = fetch_year(meta["lat"], meta["lon"], model, year, today)
                if not hourly:
                    continue
                part = pd.DataFrame(hourly)
                frames.append(part)
                n_wind = part["wind_direction_10m"].notna().sum()
                print(f"  {year}: {len(part)} ชม. (มีทิศลมจริง {n_wind} ชม.)")
                time.sleep(0.5)

            df = pd.concat(frames, ignore_index=True)
            df = df.rename(columns={"time": "datetime_utc"})
            df["station_id"] = sid
            df["role"] = meta["role"]
            df["wind_model"] = model
            df.to_csv(ckpt, index=False, encoding="utf-8-sig")

    all_df = pd.concat(
        [pd.read_csv(p) for p in sorted(CHECKPOINT_DIR.glob("*.csv"))], ignore_index=True
    )
    out_path = RAW_DIR / "wind_hourly_raw.csv"
    all_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nบันทึกข้อมูลลม {len(all_df)} แถว ไว้ที่ {out_path}")


if __name__ == "__main__":
    main()
