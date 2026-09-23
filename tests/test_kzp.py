import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline.kzp import _member_name, iter_csv, iter_zip
from pipeline.names import Chain
from tests.helpers import csv_text, make_zip

LIDL = Chain("lidl", "Lidl")


class KzpTest(unittest.TestCase):
    def test_rows(self):
        text = csv_text([
            ["14218", "114 - Габрово/ул. Свищовска 68", "Слънчогледово олио 1Л", "6810910", "42", "2.04", ""],
            ["68134", "Ф01 - ОБОРИЩЕ", "Прясно мляко 1Л", "001102", "6", "2,19", "1,89"],
            ["68134", "Ф01 - ОБОРИЩЕ", "", "000000", "6", "9.99", ""],
            ["68134", "Ф01 - ОБОРИЩЕ", "Фалшива промоция", "1", "6", "1.00", "1.20"],
        ])
        rows = list(iter_csv(text, LIDL))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].price, 2.04)
        self.assertIsNone(rows[0].promo)
        self.assertEqual((rows[1].promo, rows[1].retail, rows[1].price), (1.89, 2.19, 1.89))
        self.assertEqual(rows[1].ekatte, "68134")
        self.assertIsNone(rows[2].promo)  # промо цена ≥ редовна → не е промоция

    def test_semicolon_and_truncated(self):
        text = ('Населено място;Търговски обект;Наименование на продукта;Код на продукта;Категория;'
                'Цена на дребно;Цена в промоция\n14218;Обект;Мляко;1;6;1.50;\n14218;Обект;Отрязан')
        rows = list(iter_csv(text, LIDL))
        self.assertEqual([r.name for r in rows], ["Мляко"])

    def test_zip_and_cp437_names(self):
        with tempfile.TemporaryDirectory() as t:
            p = make_zip(Path(t) / "a.zip", {"Лидл България_131071587.csv": csv_text([["68134", "Л1", "Мляко 3.6% 1Л", "5", "6", "1.35", ""]])})
            rows = list(iter_zip(p))
            self.assertEqual((rows[0].chain.id, rows[0].price), ("lidl", 1.35))
        info = zipfile.ZipInfo("Лидл.csv".encode("utf-8").decode("cp437"))
        info.flag_bits = 0
        self.assertEqual(_member_name(info), "Лидл.csv")


if __name__ == "__main__":
    unittest.main()
