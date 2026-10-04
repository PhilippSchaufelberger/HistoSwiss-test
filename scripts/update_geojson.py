#!/usr/bin/env python3
"""
Liest neue Histopics-Beiträge aus dem WordPress-RSS-Feed,
extrahiert lat/lng, Bild, Jahr, Kanton, Autor etc. und ergänzt test-all.geojson.
Idempotent: bestehende POIs werden anhand 'poi' erkannt und nicht dupliziert.
"""
import json
import re
import math
import os

import feedparser
from bs4 import BeautifulSoup

# ---------------- Konfiguration ----------------
GEOJSON_FILE = "test-all.geojson"
FEED_URL     = "https://histoswiss.ch/histopics/feed/"
KFR_LAT      = 47.365137
KFR_LNG      = 8.527741
KATEGORIE    = "Histopics"
# ------------------------------------------------

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def extract_iframe_coords(html):
    # 1. Versuch: der shortcode (falls im Feed enthalten)
    m = re.search(r'\[histopics_iframe\s+lat="([\-\d.]+)"\s+lng="([\-\d.]+)"', html)
    if m:
        return float(m.group(1)), float(m.group(2))
    # 2. Versuch: Google-Maps-Link  destination=lat,lng
    m = re.search(r'destination=([\-\d.]+),([\-\d.]+)', html)
    if m:
        return float(m.group(1)), float(m.group(2))
    # 3. Versuch: Google-Maps  q=lat,lng
    m = re.search(r'[?&]q=([\-\d.]+),([\-\d.]+)', html)
    if m:
        return float(m.group(1)), float(m.group(2))
    # 4. Versuch: wikishootme  lat=..&lng=..
    m = re.search(r'lat=([\-\d.]+)&(?:amp;)?lng=([\-\d.]+)', html)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None

def extract_poi_id(html):
    """Sucht 'Histopics-XXXX' irgendwo im HTML (meist in Bild-URL)."""
    m = re.search(r"Histopics-(\d+)", html)
    return f"Histopics-{m.group(1).zfill(4)}" if m else None

def extract_image_url(html):
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one(".postie-attachments img") or soup.find("img")
    return img["src"] if img and img.get("src") else None

def extract_jahr(title, html):
    m = re.search(r";\s*(\d{4})", title)
    if m:
        return int(m.group(1))
    m = re.search(r'/histopics/search/(\d{4})/', html)
    return int(m.group(1)) if m else None

def extract_kanton(html):
    m = re.search(r'/histopics/tag/CH-([A-Z]{2})/', html)
    return m.group(1) if m else None

def extract_erfasst(html):
    soup = BeautifulSoup(html, "html.parser")
    strong = soup.find("strong", string=lambda s: s and "Erfasst" in s)
    if not strong:
        return None
    person_a = strong.find_next("a")
    team_a   = person_a.find_next("a") if person_a else None
    person   = person_a.get_text(strip=True) if person_a else None
    team     = None
    if team_a:
        t = team_a.get_text(strip=True).strip("()")
        team = t.replace("Team ", "").strip()
    if not person and not team:
        return None
    result = {}
    if person: result["person"] = person
    if team:   result["team"]   = team
    return result or None

def build_name(title, poi_id):
    return f"{title} - {poi_id}"

def jahrzehnt_from_jahr(j):
    return f"{(j // 10) * 10}s" if j else None

def jahrhundert_from_jahr(j):
    return f"{(j - 1) // 100 + 1}.Jh" if j else None

def load_geojson(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_geojson(path, data):
    tmp = path + ".tmp"
    features = data["features"]
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('{"type":"FeatureCollection","features":[\n')
        for i, feat in enumerate(features):
            line = json.dumps(feat, ensure_ascii=False, separators=(",", ":"))
            if i < len(features) - 1:
                f.write(line + ",\n")
            else:
                f.write(line + "\n")
        f.write("]}")
    os.replace(tmp, path)

def main():
    print(f"Lade {GEOJSON_FILE} ...")
    geojson = load_geojson(GEOJSON_FILE)
    features = geojson["features"]
    print(f"  {len(features)} bestehende Features.")

    existing_pois = {f["properties"].get("poi") for f in features if f.get("properties")}
    max_order = max(
        (f["properties"].get("order", 0) for f in features
         if isinstance(f.get("properties", {}).get("order"), int)
         and f["properties"].get("order") != 999999),
        default=0
    )
    print(f"  Höchste order: {max_order}")

    print(f"Lade Feed {FEED_URL} ...")
    feed = feedparser.parse(FEED_URL)
    print(f"  {len(feed.entries)} Einträge im Feed.")

    neu, skip, fehler = 0, 0, 0
    for entry in feed.entries:
        html = entry.content[0].value if getattr(entry, "content", None) else entry.summary

        poi_id = extract_poi_id(html)
        if not poi_id:
            print(f"  [???] kein POI-ID im HTML: {entry.title!r}")
            fehler += 1
            continue
        if poi_id in existing_pois:
            skip += 1
            continue

        lat, lng = extract_iframe_coords(html)
        if lat is None:
            print(f"  [{poi_id}] keine Koordinaten – übersprungen.")
            fehler += 1
            continue

        jahr     = extract_jahr(entry.title, html)
        kanton   = extract_kanton(html)
        bild     = extract_image_url(html)
        erfasst  = extract_erfasst(html)
        distanz  = haversine_km(KFR_LAT, KFR_LNG, lat, lng)

        props = {
            "name":        build_name(entry.title, poi_id),
            "poi":         poi_id,
            "distanz":     { "KFR": f"{distanz:.2f} km".replace(".", ",") },
            "target_url":  entry.link,
            "form_id":     poi_id,
            "order":       max_order + 1,
            "kategorie":   KATEGORIE,
        }
        if kanton:  props["kanton"]    = kanton
        if bild:    props["image_url"] = bild
        if erfasst: props["erfasst"]   = erfasst
        if jahr:
            props["jahrzehnt"]   = jahrzehnt_from_jahr(jahr)
            props["jahrhundert"] = jahrhundert_from_jahr(jahr)

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": props,
        })
        existing_pois.add(poi_id)
        max_order += 1
        neu += 1
        print(f"  [{poi_id}] + {props['name']}")

    if neu:
        print(f"Schreibe {GEOJSON_FILE} ...")
        save_geojson(GEOJSON_FILE, geojson)
    else:
        print("Keine neuen Features.")

    print(f"Fertig: {neu} neu, {skip} bereits vorhanden, {fehler} fehlerhaft.")

if __name__ == "__main__":
    main()
