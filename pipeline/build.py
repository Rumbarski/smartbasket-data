"""Дневна обработка: архивите на КЗП → файлове за приложението (папка v1/).

    python -m pipeline.build --zips .cache/zips --prev prev --out site

`--prev` е предишното съдържание на клона `data` (история и координати).
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import zlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .catalog import RULES, fits
from .geo import fetch_osm_shops, load_ekatte, match_store
from .kzp import download, iter_zip, log, zip_path
from .names import clean_store_label, parse_size, product_key, store_id

EPOCH = date(2025, 1, 1)
HIST_BUCKETS = 32
HIST_DAYS = 400
STALE_DAYS = 3  # обект без данни по-дълго не се смята за актуален
LIST_DAYS = 14  # обектите от последните 14 дни влизат в списъка
OSM_REFRESH_DAYS = 7

CATEGORY_NAMES = {
    1: "Хляб бял", 2: "Хляб „Добруджа“", 3: "Хляб ръжен и пълнозърнест", 4: "Хляб типов",
    5: "Кори за баница", 6: "Прясно мляко", 7: "Кисело мляко", 8: "Сирене краве насипно",
    9: "Сирене краве пакетирано", 10: "Кашкавал насипен", 11: "Кашкавал пакетиран",
    12: "Краве масло", 13: "Извара насипна", 14: "Извара пакетирана", 15: "Пиле цяло",
    16: "Пилешко филе", 17: "Пилешки бут", 18: "Свинска плешка", 19: "Свински бут",
    20: "Свинско филе", 21: "Свински врат", 22: "Свинско за готвене", 23: "Телешки шол",
    24: "Телешко за готвене", 25: "Кайма", 26: "Кренвирши и наденици",
    27: "Колбаси варени и шунка", 28: "Колбаси сурово-сушени", 29: "Скумрия",
    30: "Риба", 31: "Яйца M", 32: "Яйца L", 33: "Боб", 34: "Леща", 35: "Ориз",
    36: "Макаронени изделия", 37: "Спагети", 38: "Захар", 39: "Сол", 40: "Брашно тип 500",
    41: "Брашно други", 42: "Олио слънчогледово", 43: "Маслиново масло", 44: "Оцет винен",
    45: "Оцет ябълков", 46: "Боб консерва", 47: "Грах консерва", 48: "Домати консерва",
    49: "Лютеница", 50: "Лимони", 51: "Портокали", 52: "Банани", 53: "Ябълки", 54: "Домати",
    55: "Лук", 56: "Моркови", 57: "Зеле", 58: "Краставици", 59: "Чесън", 60: "Гъби",
    61: "Картофи", 62: "Маслини", 63: "Бебешка каша", 64: "Бебешко пюре",
    65: "Адаптирано мляко", 66: "Бисквити", 67: "Кроасани", 68: "Баници", 69: "Шоколад",
    70: "Кафе мляно", 71: "Кафе на зърна", 72: "Чай", 73: "Минерална вода", 74: "Бира",
    75: "Вино бяло", 76: "Вино червено", 77: "Ракия", 78: "Цигари", 79: "Препарат за съдове",
    80: "Четки за зъби", 81: "Паста за зъби", 82: "Шампоан", 83: "Сапун", 84: "Мокри кърпи",
    85: "Тоалетна хартия",
    **{c: "Лекарства" for c in range(86, 102)},
}


def off(d: date) -> int:
    return (d - EPOCH).days


def from_off(n: int) -> date:
    return EPOCH + timedelta(days=n)


def bucket(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) % HIST_BUCKETS


def r2(v: float) -> float:
    return round(v + 1e-9, 2)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class State:
    def __init__(self) -> None:
        self.stores: dict[str, dict] = {}
        self.products: dict[str, dict[str, list]] = defaultdict(dict)  # chain → key → [name, cat]
        self.chain_names: dict[str, str] = {}
        self.fit_cache: dict[tuple[str, str], list] = {}
        # (sid, key) → (ден, цена, дребно, промо)
        self.cur: dict[tuple[str, str], tuple[int, float, float | None, int]] = {}
        self.min_prior: dict[tuple[str, str], float] = {}
        # (sid, sku) → (ден, (норм, ключ, цена, промо, прибл.))
        self.sku_cur: dict[tuple[str, str], tuple[int, tuple]] = {}
        self.sku_min_prior: dict[tuple[str, str], float] = {}
        self.hist: dict[tuple[str, str], dict[int, tuple[float, int]]] = defaultdict(dict)
        self.sku_hist: dict[tuple[str, str], dict[int, tuple[float, int]]] = defaultdict(dict)
        self.days: list[date] = []


def process_day(st: State, d: date, path: Path, in_window: bool) -> int:
    day = off(d)
    prices: dict[tuple[str, str], list[float]] = defaultdict(list)
    promos: dict[tuple[str, str], int] = defaultdict(int)
    day_sku: dict[tuple[str, str], tuple] = {}
    n = 0
    for row in iter_zip(path):
        price = row.price
        if price is None:
            continue
        n += 1
        chain = row.chain.id
        st.chain_names[chain] = row.chain.name
        key = product_key(row.code, row.name)
        sid = store_id(chain, row.ekatte, row.store)
        s = st.stores.get(sid)
        if s is None:
            s = st.stores[sid] = {"chain": chain, "ekatte": row.ekatte, "label": row.store, "last": day}
        elif day > s["last"]:
            s["last"] = day
        if key not in st.products[chain]:
            st.products[chain][key] = [row.name, row.cat]
        promo = 1 if row.promo is not None else 0
        prices[(chain, key)].append(price)
        promos[(chain, key)] += promo

        fl = st.fit_cache.get((chain, key))
        if fl is None:
            fl = st.fit_cache[(chain, key)] = fits(row.name, row.cat or 0)
        for f in fl:
            norm = price * f.factor
            k = (sid, f.sku)
            old = day_sku.get(k)
            better = (
                old is None
                or (old[4] and not f.approx)
                or (old[4] == int(f.approx) and norm < old[0])
            )
            if better:
                day_sku[k] = (norm, key, price, promo, int(f.approx))

        if in_window:
            ck = (sid, key)
            prev = st.cur.get(ck)
            if prev is not None and prev[0] < day:
                mp = st.min_prior.get(ck)
                st.min_prior[ck] = prev[1] if mp is None else min(mp, prev[1])
            st.cur[ck] = (day, price, row.retail, promo)

    for ck, vals in prices.items():
        st.hist[ck][day] = (r2(statistics.median(vals)), 1 if promos[ck] * 2 > len(vals) else 0)

    by_chain: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for (sid, sku), v in day_sku.items():
        by_chain[(st.stores[sid]["chain"], sku)].append(v)
        if in_window:
            ck = (sid, sku)
            prev = st.sku_cur.get(ck)
            if prev is not None and prev[0] < day:
                mp = st.sku_min_prior.get(ck)
                st.sku_min_prior[ck] = prev[1][0] if mp is None else min(mp, prev[1][0])
            st.sku_cur[ck] = (day, v)
    for ck, vals in by_chain.items():
        norms = [v[0] for v in vals]
        st.sku_hist[ck][day] = (r2(statistics.median(norms)), 1 if sum(v[3] for v in vals) * 2 > len(vals) else 0)
    st.days.append(d)
    return n


def merge_history(target: dict, prev_items: dict, chain: str, keep_from: int) -> None:
    for key, series in (prev_items or {}).items():
        dest = target[(chain, key)]
        for o, price, promo in series:
            if o >= keep_from and o not in dest:
                dest[o] = (price, promo)


def load_prev(st: State, prev: Path | None, keep_from: int) -> dict:
    meta = read_json(prev / "v1" / "meta.json", {}) if prev else {}
    if not prev or not meta:
        return {}
    for chain in meta.get("chains", {}):
        for b in range(HIST_BUCKETS):
            data = read_json(prev / "v1" / "hist" / chain / f"{b}.json", {})
            merge_history(st.hist, data.get("items"), chain, keep_from)
        data = read_json(prev / "v1" / "skuhist" / f"{chain}.json", {})
        merge_history(st.sku_hist, data.get("items"), chain, keep_from)
    return meta


def geocode(st: State, sids: list[str], ekatte: dict, prev: Path | None, today: date, use_osm: bool) -> dict:
    cache = read_json(prev / "v1" / "geo.json", {}) if prev else {}
    stores = cache.get("stores", {})
    osm_at = cache.get("osm_at")
    need = [sid for sid in sids if stores.get(sid, [None, None, "city"])[2] != "osm"]
    stale = not osm_at or (today - date.fromisoformat(osm_at)).days >= OSM_REFRESH_DAYS
    new = [sid for sid in need if sid not in stores]
    if use_osm and need and (stale or new):
        try:
            shops = fetch_osm_shops()
            log(f"OSM: {len(shops)} обекта на веригите")
            osm_at = today.isoformat()
            for sid in need:
                s = st.stores[sid]
                city = ekatte.get(s["ekatte"])
                ll = (city[4], city[5]) if city and city[4] is not None else None
                hit = match_store(s["chain"], clean_store_label(s["label"]), city[0] if city else "", ll, shops)
                if hit:
                    stores[sid] = [hit["lat"], hit["lng"], "osm"]
        except Exception as e:  # мрежа, лимит — ще опитаме следващия път
            log(f"⚠ OSM: {e}")
    for sid in sids:
        if sid not in stores or stores[sid][2] != "osm":
            city = ekatte.get(st.stores[sid]["ekatte"])
            if city and city[4] is not None:
                stores[sid] = [city[4], city[5], "city"]
    return {"osm_at": osm_at, "stores": {k: v for k, v in stores.items() if k in st.stores}}


def build(zips: Path, out: Path, prev: Path | None, today: date, window: int, backfill: int,
          allow_download: bool, use_osm: bool) -> dict:
    prev_meta = read_json(prev / "v1" / "meta.json", {}) if prev else {}
    first_run = not prev_meta
    span = backfill if first_run else window
    wanted = [today - timedelta(days=i) for i in range(span)]
    if allow_download:
        log(f"Архиви ({'първо пускане' if first_run else 'последни'} {span} дни):")
        for d in wanted:
            download(d, zips)
    days = sorted(d for d in wanted if zip_path(zips, d).exists())
    if not days:
        raise SystemExit("Няма нито един архив от КЗП за обработка.")
    latest = days[-1]
    window_start = latest - timedelta(days=window - 1)

    st = State()
    keep_from = off(latest) - HIST_DAYS
    prev_meta = load_prev(st, prev, keep_from) or prev_meta
    total = 0
    for d in days:
        n = process_day(st, d, zip_path(zips, d), d >= window_start)
        total += n
        log(f"  {d}: {n} реда")
    latest_off = off(latest)

    ekatte = load_ekatte()
    listed = sorted(sid for sid, s in st.stores.items() if latest_off - s["last"] <= LIST_DAYS)
    geo = geocode(st, listed, ekatte, prev, today, use_osm)

    if out.exists():
        shutil.rmtree(out)
    v1 = out / "v1"

    # Обекти и градове
    stores_out = []
    cities: dict[str, dict] = {}
    for sid in listed:
        s = st.stores[sid]
        ll = geo["stores"].get(sid)
        stores_out.append({
            "id": sid, "c": s["chain"], "e": s["ekatte"], "l": s["label"], "n": clean_store_label(s["label"]),
            "lat": ll[0] if ll else None, "lng": ll[1] if ll else None, "g": ll[2] if ll else None,
            "last": from_off(s["last"]).isoformat(),
        })
        city = ekatte.get(s["ekatte"])
        c = cities.setdefault(s["ekatte"], {
            "e": s["ekatte"], "n": city[0] if city else s["ekatte"], "t": city[1] if city else "",
            "o": city[2] if city else "", "lat": city[4] if city else None, "lng": city[5] if city else None,
            "s": defaultdict(int),
        })
        c["s"][s["chain"]] += 1
    write_json(v1 / "stores.json", stores_out)
    write_json(v1 / "cities.json", sorted(
        ({**c, "s": dict(c["s"])} for c in cities.values()), key=lambda c: (-sum(c["s"].values()), c["n"])))
    write_json(v1 / "geo.json", geo)

    # Цени по обекти
    per_store: dict[str, dict] = defaultdict(lambda: {"p": {}, "s": {}})
    # Актуално е само това, което обектът е подал в последния си отчет.
    for (sid, key), (day, price, retail, promo) in st.cur.items():
        last = st.stores[sid]["last"]
        if day != last or latest_off - last > STALE_DAYS:
            continue
        mp = st.min_prior.get((sid, key))
        per_store[sid]["p"][key] = [r2(price), r2(retail) if retail else None, promo, r2(mp) if mp is not None else None]
    for (sid, sku), (day, v) in st.sku_cur.items():
        last = st.stores[sid]["last"]
        if day != last or latest_off - last > STALE_DAYS:
            continue
        norm, key, price, promo, approx = v
        mp = st.sku_min_prior.get((sid, sku))
        per_store[sid]["s"][sku] = [key, r2(price), r2(norm), promo, approx, r2(mp) if mp is not None else None]
    for sid, data in per_store.items():
        day = max((st.cur[(sid, k)][0] for k in data["p"]), default=latest_off)
        write_json(v1 / "prices" / f"{sid}.json", {"d": from_off(day).isoformat(), **data})

    # Продукти по вериги (с медианата за последния ден)
    chains_meta = {}
    for chain, items in st.products.items():
        out_items = {}
        for key, (name, cat) in items.items():
            h = st.hist.get((chain, key), {})
            last_day = max(h) if h else None
            if last_day is None or latest_off - last_day > LIST_DAYS:
                continue
            size = parse_size(name, cat)
            out_items[key] = [
                name, cat,
                size.qty if size else None, size.unit if size else None, 1 if size and size.per_kg else 0,
                h[last_day][0], h[last_day][1], from_off(last_day).isoformat(),
            ]
        write_json(v1 / "products" / f"{chain}.json", {"items": out_items})
        chains_meta[chain] = {
            "name": st.chain_names.get(chain, chain),
            "stores": sum(1 for s in stores_out if s["c"] == chain),
            "products": len(out_items),
        }

    # История (медиана по веригата)
    for chain in chains_meta:
        buckets: dict[int, dict] = defaultdict(dict)
        for (c, key), series in st.hist.items():
            if c != chain:
                continue
            pts = sorted((o, p, pr) for o, (p, pr) in series.items() if o >= keep_from)
            if pts:
                buckets[bucket(key)][key] = [list(x) for x in pts]
        for b in range(HIST_BUCKETS):
            write_json(v1 / "hist" / chain / f"{b}.json", {"epoch": EPOCH.isoformat(), "items": buckets.get(b, {})})
        sku_items = {}
        for (c, sku), series in st.sku_hist.items():
            if c == chain:
                sku_items[sku] = [list(x) for x in sorted((o, p, pr) for o, (p, pr) in series.items() if o >= keep_from)]
        write_json(v1 / "skuhist" / f"{chain}.json", {"epoch": EPOCH.isoformat(), "items": sku_items})

    hist_days = sorted({o for series in st.sku_hist.values() for o in series})
    meta = {
        "v": 1,
        "date": latest.isoformat(),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "КЗП · kolkostruva.bg (отворени данни)",
        "epoch": EPOCH.isoformat(),
        "historyFrom": from_off(hist_days[0]).isoformat() if hist_days else latest.isoformat(),
        "chains": chains_meta,
        "stores": len(stores_out),
        "cities": len(cities),
        "rows": total,
        "categories": {str(k): v for k, v in CATEGORY_NAMES.items()},
        "sku": [{"id": r.id, "name": r.name, "size": r.size, "unit": r.unit} for r in RULES],
        "histBuckets": HIST_BUCKETS,
    }
    write_json(v1 / "meta.json", meta)
    (out / "README.md").write_text(
        "# Smart Basket BG — цени\n\nГенерирано автоматично от отворените данни на КЗП "
        f"(kolkostruva.bg). Последен ден: {latest.isoformat()}.\n", encoding="utf-8")

    # Кешът пази само прозореца (+ резерв) — историята вече е в изхода.
    for p in zips.glob("*.zip"):
        try:
            if date.fromisoformat(p.stem) < window_start - timedelta(days=5):
                p.unlink()
        except ValueError:
            pass
    log(f"Готово: {latest} · {len(stores_out)} обекта · {sum(c['products'] for c in chains_meta.values())} продукта")
    return meta


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zips", type=Path, default=Path(".cache/zips"))
    ap.add_argument("--out", type=Path, default=Path("site"))
    ap.add_argument("--prev", type=Path, default=None)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--window", type=int, default=31)
    ap.add_argument("--backfill", type=int, default=90)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-osm", action="store_true")
    a = ap.parse_args(argv)
    today = a.today or datetime.now(timezone(timedelta(hours=3))).date()
    prev = a.prev if a.prev and a.prev.exists() else None
    build(a.zips, a.out, prev, today, a.window, a.backfill, not a.no_download, not a.no_osm)


if __name__ == "__main__":
    main()
