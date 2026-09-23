import unittest

from pipeline.geo import haversine_km, match_store

SHOPS = [
    {"chain": "lidl", "lat": 42.66, "lng": 23.28, "street": "булевард „Цар Борис III“", "house": "145", "city": "София", "name": "Lidl", "osm": "n1"},
    {"chain": "lidl", "lat": 42.65, "lng": 23.38, "street": "улица Филип Кутев", "house": "1", "city": "София", "name": "Lidl", "osm": "n2"},
    {"chain": "kaufland", "lat": 42.87, "lng": 25.32, "street": "Свищовска", "house": "68", "city": "Габрово", "name": "Kaufland", "osm": "w3"},
]
SOFIA = (42.6977, 23.3219)


class GeoTest(unittest.TestCase):
    def test_distance(self):
        self.assertAlmostEqual(haversine_km(SOFIA, (42.1354, 24.7453)), 131.9, delta=1.5)

    def test_match_by_street(self):
        hit = match_store("lidl", "София, бул. Цар Борис III 145", "София", SOFIA, SHOPS)
        self.assertEqual(hit["osm"], "n1")
        self.assertIsNone(match_store("lidl", "София, ж.к. Люлин 5", "София", SOFIA, SHOPS))

    def test_single_in_city(self):
        hit = match_store("kaufland", "Габрово", "Габрово", (42.8742, 25.3187), SHOPS)
        self.assertEqual(hit["osm"], "w3")


if __name__ == "__main__":
    unittest.main()
