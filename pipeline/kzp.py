"""Сваляне и четене на дневните архиви на КЗП „Колко струва“.

Архивът е https://kolkostruva.bg/opendata_files/ГГГГ-ММ-ДД.zip с по един CSV
файл на верига (UTF-8, запетая, кавички) и колони:
„Населено място“ (ЕКАТТЕ), „Търговски обект“, „Наименование на продукта“,
„Код на продукта“, „Категория“, „Цена на дребно“, „Цена в промоция“.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .names import Chain, chain_from_filename, ekatte_code

BASE_URL = "https://kolkostruva.bg/opendata_files"
# Сървърът връща 403 без браузърен User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def log(*a) -> None:
    print(*a, file=sys.stderr, flush=True)


def zip_path(zips: Path, day: date) -> Path:
    return zips / f"{day.isoformat()}.zip"


def download(day: date, zips: Path, timeout: int = 90, retries: int = 2) -> Path | None:
    """Сваля архива за деня; връща пътя или None, ако още го няма."""
    dest = zip_path(zips, day)
    if dest.exists():
        return dest
    zips.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{day.isoformat()}.zip"
    for attempt in range(retries + 1):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}), timeout=timeout) as r:
                data = r.read()
        except HTTPError as e:
            if e.code in (403, 404):
                log(f"  {day}: няма архив (HTTP {e.code})")
                return None
            log(f"  {day}: HTTP {e.code}, опит {attempt + 1}")
        except (URLError, TimeoutError, OSError) as e:
            log(f"  {day}: {e}, опит {attempt + 1}")
        else:
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    bad = z.testzip()
                if bad:
                    raise zipfile.BadZipFile(bad)
            except zipfile.BadZipFile as e:
                log(f"  {day}: повреден архив ({e}), опит {attempt + 1}")
            else:
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(dest)
                log(f"  {day}: {len(data) / 1e6:.1f} MB")
                return dest
        time.sleep(3 * (attempt + 1))
    return None


@dataclass(frozen=True)
class Row:
    chain: Chain
    ekatte: str
    store: str
    name: str
    code: str
    cat: int | None
    retail: float | None
    promo: float | None

    @property
    def price(self) -> float | None:
        """Цената, която клиентът плаща днес."""
        return self.promo if self.promo is not None else self.retail


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    if not s or s.count(".") > 1:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if 0 < v < 100000 else None


def _int(value: str | None) -> int | None:
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def _member_name(info: zipfile.ZipInfo) -> str:
    """Имената без UTF-8 флаг Python ги чете като cp437 — възстановяваме ги."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", errors="replace")
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename


def _decode(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        # Понякога файлът е отрязан по средата на символ — пазим останалото.
        try:
            text = data.decode("cp1251")
            if re.search(r"[А-Яа-я]{3}", text):
                return text
        except UnicodeDecodeError:
            pass
        log(f"  ⚠ {label}: UTF-8 грешка при байт {e.start} — заменям")
        return data.decode("utf-8-sig", errors="replace")


_COLS = {
    "ekatte": ("населено",),
    "store": ("обект",),
    "name": ("наименование", "продукт"),
    "code": ("код",),
    "cat": ("категор",),
    "retail": ("дребно",),
    "promo": ("промоц",),
}


def _columns(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    low = [h.strip().lower() for h in header]
    for key, needles in _COLS.items():
        for i, h in enumerate(low):
            if i in idx.values():
                continue
            if needles[0] in h and (key != "name" or "код" not in h):
                idx[key] = i
                break
    return idx


def iter_csv(text: str, chain: Chain) -> Iterator[Row]:
    first = text.split("\n", 1)[0]
    delim = max([",", ";", "\t"], key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        return
    cols = _columns(header)
    if not {"store", "name", "retail"} <= cols.keys():
        log(f"  ⚠ {chain.name}: непознати колони {header}")
        return
    n = len(header)
    for rec in reader:
        if len(rec) < n - 1:
            continue  # отрязан ред
        get = lambda k: rec[cols[k]] if k in cols and cols[k] < len(rec) else ""
        name = get("name").strip()
        retail = _num(get("retail"))
        promo = _num(get("promo"))
        if not name or (retail is None and promo is None):
            continue
        if promo is not None and retail is not None and promo >= retail:
            promo = None  # „промоция“ без намаление
        yield Row(chain, ekatte_code(get("ekatte")), get("store").strip(), name,
                  get("code").strip(), _int(get("cat")), retail, promo)


def iter_zip(path: Path) -> Iterator[Row]:
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            fname = _member_name(info)
            if info.is_dir() or not fname.lower().endswith(".csv"):
                continue
            chain = chain_from_filename(fname)
            try:
                data = z.read(info)
            except (zipfile.BadZipFile, OSError) as e:
                log(f"  ⚠ {fname}: {e}")
                continue
            yield from iter_csv(_decode(data, fname), chain)
