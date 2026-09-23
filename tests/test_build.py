import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline.build import build, off
from tests.helpers import csv_text, make_zip

SOF_LIDL = "Л12 - София/бул. Цар Борис III 145"
GAB_LIDL = "114 - Габрово/ул. Свищовска 68"
SOF_KAUF = "К01 - София/Младост 1"


def day_files(coffee_lidl, coffee_promo="", with_yog=True):
    lidl = [
        ["68134", SOF_LIDL, "ПРЯСНО МЛЯКО ВЕРЕЯ 3.6% 1Л", "101", "6", "1.35", ""],
        ["68134", SOF_LIDL, "КАФЕ МЛЯНО 250Г", "102", "70", str(coffee_lidl), coffee_promo],
        ["14218", GAB_LIDL, "ПРЯСНО МЛЯКО ВЕРЕЯ 3.6% 1Л", "101", "6", "1.39", ""],
        ["68134", SOF_LIDL, "Банани на кг", "103", "52", "1.69", ""],
    ]
    if with_yog:
        lidl.append(["68134", SOF_LIDL, "КИСЕЛО МЛЯКО 3,6% 400Г", "104", "7", "0.89", ""])
    kauf = [
        ["68134", SOF_KAUF, "ПРЯСНО МЛЯКО БОЖЕНЦИ 3.6% 1Л", "9001", "6", "1.29", ""],
        ["68134", SOF_KAUF, "ПРЯСНО МЛЯКО МАДЖАРОВ 3.6% 1Л", "9002", "6", "1.49", ""],
        ["68134", SOF_KAUF, "КРАВЕ МАСЛО 125 ГР", "9003", "12", "1.59", ""],
    ]
    return {"Лидл България_131071587.csv": csv_text(lidl), "Кауфланд България_131129282.csv": csv_text(kauf)}


class BuildTest(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            zips = t / "zips"
            make_zip(zips / "2026-09-15.zip", day_files(4.49))
            make_zip(zips / "2026-09-16.zip", day_files(4.29))
            make_zip(zips / "2026-09-17.zip", day_files(4.49, "3.59", with_yog=False))
            out = t / "site"
            meta = build(zips, out, None, date(2026, 9, 18), window=31, backfill=5,
                         allow_download=False, use_osm=False)
            self.assertEqual(meta["date"], "2026-09-17")
            self.assertEqual(set(meta["chains"]), {"lidl", "kaufland"})

            stores = json.loads((out / "v1/stores.json").read_text())
            self.assertEqual(len(stores), 3)
            sof = next(s for s in stores if s["l"] == SOF_LIDL)
            self.assertEqual(sof["n"], "София, бул. Цар Борис III 145")
            self.assertEqual(sof["g"], "city")
            self.assertAlmostEqual(sof["lat"], 42.6977)

            cities = json.loads((out / "v1/cities.json").read_text())
            self.assertEqual(cities[0]["n"], "София")
            self.assertEqual(cities[0]["s"], {"lidl": 1, "kaufland": 1})

            p = json.loads((out / f"v1/prices/{sof['id']}.json").read_text())
            self.assertEqual(p["d"], "2026-09-17")
            coffee = p["p"]["102"]
            self.assertEqual(coffee, [3.59, 4.49, 1, 4.29])  # цена, редовна, промо, мин. 30 дни
            self.assertNotIn("104", p["p"])  # обектът е подал отчет днес без киселото мляко
            self.assertEqual(p["s"]["milk36"][:3], ["101", 1.35, 1.35])
            self.assertEqual(p["s"]["banana"][2], 1.69)
            self.assertEqual(p["s"]["coffee"][2], round(3.59 * 0.225 / 0.25, 2))

            kauf = next(s for s in stores if s["c"] == "kaufland")
            pk = json.loads((out / f"v1/prices/{kauf['id']}.json").read_text())
            self.assertEqual(pk["s"]["milk36"][0], "9001")  # най-евтиното подходящо
            self.assertEqual(pk["s"]["butter"][2:5], [3.18, 0, 1])  # 125 г → 250 г, прибл.

            prods = json.loads((out / "v1/products/lidl.json").read_text())["items"]
            self.assertEqual(prods["101"][0], "ПРЯСНО МЛЯКО ВЕРЕЯ 3.6% 1Л")
            self.assertEqual(prods["101"][5], 1.37)  # медиана от София и Габрово

            sh = json.loads((out / "v1/skuhist/lidl.json").read_text())["items"]
            self.assertEqual(len(sh["milk36"]), 3)

            # Второ пускане: само нов ден, историята идва от предишния изход.
            zips2 = t / "zips2"
            make_zip(zips2 / "2026-09-18.zip", day_files(4.49))
            out2 = t / "site2"
            build(zips2, out2, out, date(2026, 9, 18), window=1, backfill=5,
                  allow_download=False, use_osm=False)
            sh2 = json.loads((out2 / "v1/skuhist/lidl.json").read_text())["items"]
            self.assertEqual([x[0] for x in sh2["milk36"]], [off(date(2026, 9, d)) for d in (15, 16, 17, 18)])
            p2 = json.loads((out2 / f"v1/prices/{sof['id']}.json").read_text())
            self.assertEqual(p2["p"]["102"][:3], [4.49, 4.49, 0])


if __name__ == "__main__":
    unittest.main()
