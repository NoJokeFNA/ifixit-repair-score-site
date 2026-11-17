import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from device_images import build_image_manifest, device_image
from french_repairability_scraper import FrenchRepairabilityScraper
from french_source_verification import apply_verification


class ImageEvidenceTests(unittest.TestCase):
    def test_large_unexplained_image_loss_blocks_publication(self):
        from copy import deepcopy

        from data_quality import compare_snapshots

        before = [
            {
                "name": f"Phone {index}",
                "brand": "Example",
                "repairability_score": 6,
                "france_repairability_score": None,
                "image": {"thumbnail": f"https://guide-images.cdn.ifixit.com/igi/{index}.thumbnail"},
            }
            for index in range(20)
        ]
        after = deepcopy(before)
        for row in after[:5]:
            del row["image"]
        sources = [{"source_url": "https://www.indicereparabilite.fr/produit/phone/"}]
        report = compare_snapshots(sources, sources, before, after)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(error.startswith("device_images:") for error in report["errors"]))

    def test_untrusted_or_missing_image_urls_are_not_published(self):
        for value in (
            None,
            {},
            {"thumbnail": "http://guide-images.cdn.ifixit.com/igi/a.thumbnail"},
            {"thumbnail": "https://example.com/igi/a.thumbnail"},
        ):
            self.assertIsNone(device_image(value, "https://www.ifixit.com/Device/Phone"))

    def test_previous_thumbnail_is_reused_only_for_the_same_image_id(self):
        image = {"image_id": 2, "thumbnail": "https://guide-images.cdn.ifixit.com/igi/new.thumbnail"}
        old = {"Phone": {"image_id": 1, "local": "assets/devices/1.jpg"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assets/devices/1.jpg"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"previous photo")
            session = Mock()
            session.__enter__ = Mock(return_value=session)
            session.__exit__ = Mock(return_value=None)
            session.get.side_effect = requests.ConnectionError("offline")
            result = build_image_manifest(
                [{"title": "Phone", "image": image}], old, directory, session_factory=lambda: session
            )
            self.assertIsNone(result["Phone"]["local"])
            self.assertEqual(path.read_bytes(), b"previous photo")

    def test_unchanged_image_uses_the_cached_local_asset_without_a_request(self):
        image = {"image_id": 1, "thumbnail": "https://guide-images.cdn.ifixit.com/igi/photo.thumbnail"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assets/devices/1.jpg"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"photo")
            factory = Mock(side_effect=AssertionError("unexpected request"))
            result = build_image_manifest(
                [{"title": "Phone", "image": image}],
                {"Phone": {**image, "local": "assets/devices/1.jpg"}},
                directory,
                session_factory=factory,
            )
            self.assertEqual(result["Phone"]["local"], "assets/devices/1.jpg")
            factory.assert_not_called()


class CalculationSheetTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {
            "score": 6.0,
            "sha256": hashlib.sha256(b"reviewed sheet").hexdigest(),
            "calculation_sheet_url": "https://www.indicereparabilite.fr/sheet.png",
            "calculation_total": 59.6,
        }

    def test_checked_sheet_retains_both_catalogue_and_calculation_values(self):
        row = {"repairability_score": 4.8}
        apply_verification(row, self.evidence, b"reviewed sheet", True)
        self.assertEqual(row["repairability_score"], 6.0)
        self.assertEqual(row["catalogue_score"], 4.8)
        self.assertEqual(row["verification"], "sheet_checked")

    def test_changed_or_detached_sheet_cannot_keep_an_old_verified_score(self):
        for content, attached in ((b"changed sheet", True), (b"reviewed sheet", False)):
            row = {
                "name": "Phone",
                "normalized_name": "phone",
                "repairability_score": 4.8,
                "source_url": "https://www.indicereparabilite.fr/produit/phone/",
            }
            apply_verification(row, self.evidence, content, attached)
            self.assertEqual(row["verification"], "review_needed")
            scraper = FrenchRepairabilityScraper()
            scraper.french_scores = [row]
            matched = scraper.match_device({"name": "Phone"})
            self.assertEqual(matched["status"], "conflicting")
            self.assertIsNone(matched["score"])
            self.assertEqual(matched["sources"][0]["verification"], "review_needed")
