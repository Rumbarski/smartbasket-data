import unittest

from pipeline.catalog import RULES, fits


def ids(name, cat):
    return [f.sku for f in fits(name, cat)]


class CatalogTest(unittest.TestCase):
    def test_ids_unique(self):
        self.assertEqual(len({r.id for r in RULES}), len(RULES))

    def test_matches(self):
        self.assertEqual(ids("ПРЯСНО МЛЯКО БОЖЕНЦИ 3.6% 1Л.", 6), ["milk36"])
        self.assertEqual(ids("UHT 3,2% MLEKOVITA 1Л", 6), [])
        self.assertEqual(ids("КИС МЛЯКО БЕЗ ЛАКТОЗА 3.6% 400Г", 7), [])
        self.assertEqual(ids("КИСЕЛО МЛЯКО 2% БАДЖАНАШКО 400Г", 7), ["yog2"])
        self.assertEqual(ids("Банани на кг", 52), ["banana"])
        self.assertEqual(ids("ДОМАТИ REGGIA БЕЛЕНИ ЦЕЛИ 400 ГР КОНСЕРВА", 48), ["tomCan"])
        self.assertEqual(ids("700Г ДОМАТЕНО ПЮРЕ VITAL", 48), [])
        self.assertEqual(ids("500ГР ПЕНЕ CLEVER", 36), ["macaroni"])
        self.assertEqual(ids("Kайма смес, 60/40", 25), ["mince"])

    def test_factor_and_approx(self):
        f = fits("КРАВЕ МАСЛО 125 ГР CLEVER", 12)[0]
        self.assertEqual((f.sku, f.factor, f.approx), ("butter", 2.0, True))
        f = fits("МАСЛО КРАВЕ 250 Г", 12)[0]
        self.assertEqual((f.factor, f.approx), (1.0, False))
        f = fits("SOC КАЙМА СМЕС 60/40", 25)[0]
        self.assertEqual((f.factor, f.approx), (0.5, True))  # на кг → 500 г
        f = fits("Кисело мляко 3,6% ЗНП XXL", 7)[0]
        self.assertTrue(f.approx)  # разфасовката е предположена


if __name__ == "__main__":
    unittest.main()
