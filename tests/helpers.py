import io
import zipfile
from pathlib import Path

HEADER = '"Населено място","Търговски обект","Наименование на продукта","Код на продукта","Категория","Цена на дребно","Цена в промоция"\n'


def csv_text(rows):
    lines = [HEADER]
    for r in rows:
        lines.append(",".join(f'"{v}"' for v in r) + "\n")
    return "".join(lines)


def make_zip(path: Path, files: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text.encode("utf-8-sig"))
    return path
