import unittest

import pandas as pd

from clasificados_scrape import (
    clean_broker_name,
    clean_real_estate_data,
    extract_property_id,
    parse_total_properties_text,
    validate_cleaned_data,
)


class TestClasificadosScrapeUtils(unittest.TestCase):
    def test_extract_property_id(self):
        link = "https://www.clasificadosonline.com/UDRE_Detail.asp?ID=1234567"
        self.assertEqual(extract_property_id(link), "1234567")
        self.assertIsNone(extract_property_id("https://example.com/no-id"))

    def test_parse_total_properties_text(self):
        self.assertEqual(parse_total_properties_text("Total: 12,345"), 12345)
        self.assertEqual(parse_total_properties_text("Mostrando 1-20 de 9630"), 9630)
        self.assertIsNone(parse_total_properties_text(""))

    def test_clean_broker_name(self):
        broker = "ClasificadosOnline Realty de Las Flores"
        barrio = "San Juan-Las Flores"
        cleaned = clean_broker_name(broker, barrio)
        self.assertEqual(cleaned, "Realty")

    def test_clean_real_estate_data_and_validation(self):
        raw_df = pd.DataFrame(
            [
                {
                    "propertyid": "1",
                    "title": "Casa",
                    "price": "$123,000",
                    "rooms": "3 Cuartos 2 Baños",
                    "type": ", Residencial",
                    "barrio": "Santurce",
                    "pueblo": "San Juan",
                    "link": "https://x?ID=1",
                    "piclink": "https://img",
                    "broker": "ClasificadosOnline Broker",
                    "optioned": False,
                },
                {
                    "propertyid": "1",
                    "title": "Casa duplicate",
                    "price": "$123,000",
                    "rooms": "3 Cuartos 2 Baños",
                    "type": "Residencial",
                    "barrio": "Santurce",
                    "pueblo": "San Juan",
                    "link": "https://x?ID=1",
                    "piclink": "https://img",
                    "broker": "Broker",
                    "optioned": False,
                },
            ]
        )

        municipios = pd.DataFrame([{"name": "San Juan", "region": "Metro"}])
        cleaned = clean_real_estate_data(raw_df, municipios)

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.iloc[0]["region"], "Metro")
        self.assertEqual(cleaned.iloc[0]["bedrooms"], "3")
        self.assertEqual(cleaned.iloc[0]["bathrooms"], "2")
        self.assertEqual(cleaned.iloc[0]["price"], 123000.0)

        report = validate_cleaned_data(cleaned)
        self.assertEqual(report["rows"], 1)
        self.assertEqual(report["duplicate_property_id"], 0)
        self.assertEqual(report["invalid_price"], 0)


if __name__ == "__main__":
    unittest.main()
