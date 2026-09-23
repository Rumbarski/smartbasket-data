"""Координати: ЕКАТТЕ → населено място, и обекти → точка от OpenStreetMap."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .kzp import USER_AGENT, log
from .names import cyr

DATA = Path(__file__).resolve().parent.parent / "data"


def load_ekatte() -> dict[str, list]:
    """код → [име, вид, област, община, lat, lng] (Places-in-Bulgaria, MIT)."""
    return json.loads((DATA / "ekatte.json").read_text(encoding="utf-8"))


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


OVERPASS = "https://overpass-api.de/api/interpreter"
BRANDS = {
    "lidl": r"lidl",
    "kaufland": r"kaufland",
    "billa": r"billa",
    "fantastico": r"fantastico|фантастико",
    "tmarket": r"t[\s-]?market|т[\s-]?маркет",
    "cba": r"\bcba\b",
    "metro": r"\bmetro\b|\bметро\b",
    "promarket": r"pro\s?market|про\s?маркет",
}


def fetch_osm_shops(timeout: int = 180) -> list[dict]:
    """Всички супермаркети на познатите вериги в България (един заявка)."""
    brands = "|".join(BRANDS.values())
    query = f"""
[out:json][timeout:{timeout}];
area["ISO3166-1"="BG"][admin_level=2]->.bg;
nwr["shop"]["brand"~"{brands}",i](area.bg);
out center tags;
"""
    req = Request(OVERPASS, data=urlencode({"data": query}).encode(),
                  headers={"User-Agent": USER_AGENT + " SmartBasketBG-data"})
    with urlopen(req, timeout=timeout + 30) as r:
        payload = json.loads(r.read().decode("utf-8"))
    shops = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        brand = (tags.get("brand") or tags.get("name") or "").lower()
        chain = next((cid for cid, rx in BRANDS.items() if re.search(rx, brand)), None)
        if not chain:
            continue
        shops.append({
            "chain": chain,
            "lat": round(float(lat), 6),
            "lng": round(float(lon), 6),
            "street": tags.get("addr:street", ""),
            "house": tags.get("addr:housenumber", ""),
            "city": tags.get("addr:city", ""),
            "name": tags.get("name", ""),
            "osm": f"{el.get('type', 'n')[0]}{el.get('id')}",
        })
    return shops


_STOP = {"УЛ", "УЛИЦА", "БУЛ", "БУЛЕВАРД", "ЖК", "Ж", "К", "КВ", "ПЛ", "ГР", "С", "НОМЕР", "№",
         "LIDL", "ЛИДЛ", "KAUFLAND", "КАУФЛАНД", "BILLA", "БИЛЛА", "МАГАЗИН", "ХИПЕРМАРКЕТ",
         "СУПЕРМАРКЕТ", "ФАНТАСТИКО", "FANTASTICO", "МАРКЕТ", "MARKET", "Т", "T", "БЛ", "ВХ"}


def _tokens(*texts: str) -> set[str]:
    out = set()
    for t in texts:
        for w in re.findall(r"[0-9]+|[А-ЯA-Z]{3,}", cyr(t).replace("„", " ").replace("“", " ")):
            if w not in _STOP:
                out.add(w)
    return out


def match_store(chain: str, label: str, city_name: str, city_ll: tuple[float, float] | None,
                shops: list[dict]) -> dict | None:
    """Най-добрата точка от OSM за обект на КЗП (или None)."""
    cands = [s for s in shops if s["chain"] == chain]
    if city_ll:
        cands = [s for s in cands if haversine_km(city_ll, (s["lat"], s["lng"])) < 20]
    elif city_name:
        cands = [s for s in cands if cyr(s["city"]) == cyr(city_name)]
    if not cands:
        return None
    want = _tokens(label) - _tokens(city_name)
    best, best_score = None, 0.0
    for s in cands:
        have = _tokens(s["street"], s["house"], s["name"])
        if not want or not have:
            continue
        inter = len(want & have)
        score = inter / len(want | have)
        # Съвпадащо име на улица тежи повече от номер.
        if any(len(w) > 3 for w in want & have):
            score += 0.25
        if score > best_score:
            best, best_score = s, score
    if best is not None and best_score >= 0.34:
        return best
    if len(cands) == 1 and city_ll and haversine_km(city_ll, (cands[0]["lat"], cands[0]["lng"])) < 8:
        return cands[0]  # единственият обект на веригата в града
    return None
