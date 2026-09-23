import unittest

from pipeline.names import (chain_from_filename, clean_store_label, ekatte_code, parse_fat,
                            parse_size, product_key, store_id)


class NamesTest(unittest.TestCase):
    def test_chain(self):
        self.assertEqual(chain_from_filename("Лидл България_131071587.csv").id, "lidl")
        self.assertEqual(chain_from_filename("ФАНТАСТИКО (ФАНТАСТИКО ГРУП ООД)_206255903.csv").name, "Fantastico")
        self.assertEqual(chain_from_filename("Кауфланд България ЕООД енд Ко КД_131129282.csv").id, "kaufland")
        self.assertEqual(chain_from_filename("Т МАРКЕТ_123.csv").id, "tmarket")
        other = chain_from_filename("Някаква Верига ООД_999.csv")
        self.assertEqual(other.id, "nyakakva-veriga-ood")

    def test_label(self):
        self.assertEqual(clean_store_label("114 - Габрово/ул. Свищовска 68"), "Габрово, ул. Свищовска 68")
        self.assertEqual(clean_store_label("Ф01 - ОБОРИЩЕ"), "Оборище")
        self.assertEqual(clean_store_label("София, бул. Витоша 1"), "София, бул. Витоша 1")

    def test_codes(self):
        self.assertEqual(ekatte_code("7079"), "07079")
        self.assertEqual(product_key("6810910", "Олио"), "6810910")
        self.assertTrue(product_key("000000", "Олио").startswith("n"))
        self.assertEqual(product_key("", "олио  1л"), product_key("", "ОЛИО 1Л"))
        a = store_id("lidl", "68134", "Л1 - София")
        self.assertEqual(a, store_id("lidl", "68134", "л1 -  софия"))

    def test_sizes(self):
        s = parse_size("КИСЕЛО МЛЯКО 3,6% 400Г", 7)
        self.assertEqual((s.qty, s.unit), (0.4, "kg"))
        s = parse_size("МИНЕРАЛНА ВОДА МУЛТИПАК 6Х1.5Л", 73)
        self.assertEqual((s.qty, s.unit), (9.0, "l"))
        s = parse_size("БЕЛ КРАВЕ СИРЕНЕ БЕЛИИСА / 8КГ/ БСС", 8)
        self.assertTrue(s.per_kg)
        self.assertTrue(parse_size("Банани на кг", 52).per_kg)
        self.assertEqual(parse_size("ЯЙЦА М10 ПОДОВО", 31).qty, 10)
        self.assertEqual(parse_size("Тоал.хартия 3пл 8бр.", 85).qty, 8)
        self.assertAlmostEqual(parse_size("COLGATE П-ТА ЗА ЗЪБИ 125М", 81).qty, 0.125)
        self.assertAlmostEqual(parse_size("700MЛ ОЦЕТ", 44).qty, 0.7)
        self.assertIsNone(parse_size("Бял боб", 33))

    def test_fat(self):
        self.assertEqual(parse_fat("UHT 3,2% MLEKOVITA 1Л"), 3.2)
        self.assertIsNone(parse_fat("СИРЕНЕ 400Г"))


if __name__ == "__main__":
    unittest.main()
