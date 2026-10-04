#!/usr/bin/env python3
"""Einmalig: distanz_kfr -> distanz.KFR umbauen."""
import json

FILE = "test-all.geojson"

with open(FILE, "r", encoding="utf-8") as f:
    gj = json.load(f)

count = 0
for feat in gj["features"]:
    props = feat.get("properties", {})
    if "distanz_kfr" in props:
        props["distanz"] = {"KFR": props.pop("distanz_kfr")}
        count += 1

with open(FILE, "w", encoding="utf-8") as f:
    json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

print(f"{count} Features migriert.")
