"""
ดึงขอบเขตพื้นที่อุตสาหกรรมรอบมาบตาพุดจาก OpenStreetMap ผ่าน Overpass API

ดึง 2 แบบ:
- landuse=industrial  = พื้นที่นิคม/โรงงานทั่วไป
- power=plant         = โรงไฟฟ้า (บางแห่งไม่ได้ติดแท็ก landuse=industrial ไว้)

ขอเป็น "out geom" เพื่อให้ได้พิกัดทุกจุดของ polygon ไม่ใช่แค่จุดกึ่งกลาง
เพราะนิคมมาบตาพุดมีขนาดใหญ่หลายกิโลเมตร ถ้าใช้แค่จุดกึ่งกลางจะคำนวณทิศผิด

ไม่ต้องใช้ API key เซฟผลไว้ที่ data/raw/osm_industrial_sites.json
ข้อมูล OSM อยู่ภายใต้สัญญาอนุญาต ODbL ต้องให้เครดิตใน README
"""

import json
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://overpass-api.de/api/interpreter"

# กรอบพิกัดครอบสถานีทั้ง 3 แห่งบวกรัศมีเผื่ออีกประมาณ 15 กม.
# สถานีใต้สุด 225611 (12.7087) สถานีเหนือสุดคือสถานีควบคุม 717 (12.9738)
BBOX = (12.55, 101.00, 13.12, 101.40)  # south, west, north, east

QUERY = f"""
[out:json][timeout:180];
(
  way["landuse"="industrial"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["landuse"="industrial"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["power"="plant"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["power"="plant"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom tags;
"""

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_PATH = RAW_DIR / "osm_industrial_sites.json"

# Overpass ขอให้ระบุตัวตนผู้เรียกใช้ตามนโยบายการใช้งาน
HEADERS = {"User-Agent": "maptaphut-air-quality-research/1.0 (student project)"}


def fetch() -> dict:
    """เรียก Overpass API พร้อม retry เพราะเซิร์ฟเวอร์สาธารณะคิวยาวบ่อย"""
    for attempt in range(5):
        try:
            resp = requests.post(API_URL, data={"data": QUERY}, headers=HEADERS, timeout=300)
        except requests.exceptions.RequestException as e:
            print(f"  [retry] connection error: {e}")
            time.sleep(10 * (attempt + 1))
            continue
        if resp.status_code in (429, 504):
            print(f"  [retry] HTTP {resp.status_code} (เซิร์ฟเวอร์คิวเต็ม)")
            time.sleep(20 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("ดึงข้อมูล Overpass ไม่สำเร็จหลังจาก retry 5 ครั้ง")


def main():
    print("กำลังดึงข้อมูลจาก Overpass API ...")
    data = fetch()
    elements = data.get("elements", [])

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    n_geom = sum(1 for e in elements if e.get("geometry") or e.get("members"))
    named = [e["tags"].get("name:en") or e["tags"].get("name") for e in elements if e.get("tags", {}).get("name")]
    print(f"ได้ทั้งหมด {len(elements)} พื้นที่ (มีรูปร่าง polygon {n_geom} พื้นที่)")
    print(f"ในจำนวนนี้มีชื่อกำกับ {len(named)} แห่ง")
    print(f"บันทึกไว้ที่ {OUT_PATH}")


if __name__ == "__main__":
    main()
