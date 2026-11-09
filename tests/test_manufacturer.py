import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fetch_device_data import print_device_data
from utils import _DeviceDataUtils


class ManufacturerTests(unittest.TestCase):
    def test_explicit_brand_takes_precedence(self):
        category = {
            "info": [{"name": "Device Brand", "value": " Example "}],
            "ancestors": [{"namespace": "CATEGORY", "title": "Fairphone"}],
        }
        self.assertEqual(_DeviceDataUtils.device_brand(category), "Example")

    def test_fairphone_category_supplies_missing_brand(self):
        for info in [None, [], [{"name": "Device Brand", "value": " "}]]:
            with self.subTest(info=info):
                category = {"info": info, "ancestors": [{"namespace": "CATEGORY", "title": "Fairphone"}]}
                self.assertEqual(_DeviceDataUtils.device_brand(category), "Fairphone")

    def test_unverified_parent_is_not_assumed_to_be_the_brand(self):
        for title in ["Android Phone", "Phone", "Nokia Android Phone", "Fairphone 5"]:
            with self.subTest(title=title):
                self.assertIsNone(
                    _DeviceDataUtils.device_brand({"ancestors": [{"namespace": "CATEGORY", "title": title}]})
                )

    def test_wrong_namespace_does_not_supply_a_brand(self):
        self.assertIsNone(_DeviceDataUtils.device_brand({"ancestors": [{"namespace": "WIKI", "title": "Fairphone"}]}))

    def test_missing_metadata_remains_unknown(self):
        self.assertIsNone(_DeviceDataUtils.device_brand({"info": None, "ancestors": None}))

    def test_generated_device_keeps_model_and_score_separate_from_brand(self):
        client = Mock()
        client.get_category.return_value = {
            "title": "Fairphone 5",
            "repairability_score": 10,
            "info": [{"name": "Device Category", "value": "Phone"}],
            "ancestors": [{"namespace": "CATEGORY", "title": "Fairphone"}],
        }
        french_scraper = Mock()
        french_scraper.match_device.return_value = {"status": "matched", "score": 9.3, "sources": []}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("fetch_device_data.fetch_teardown_guides", return_value={}),
            patch("fetch_device_data.get_rubric_versions_for_devices", return_value=[]),
        ):
            output = Path(directory) / "devices.json"
            print_device_data(client, ["Fairphone 5"], french_scraper, str(output))
            device = json.loads(output.read_text())[0]
        self.assertEqual(device["name"], "Fairphone 5")
        self.assertEqual(device["brand"], "Fairphone")
        self.assertEqual(device["repairability_score"], 10)
        self.assertEqual(device["france_repairability_score"], 9.3)
        self.assertEqual(device["link"], "https://www.ifixit.com/Device/Fairphone_5")
