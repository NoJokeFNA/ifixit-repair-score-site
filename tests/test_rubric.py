import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fetch_device_data import generate_rubric_json


def page(version, criterion="Design for Repair"):
    return (
        f"<h1>Repairability Scoring Rubric v{version}</h1><p>Scoring Factors</p>"
        f"<table><tr><th>Criterion</th><th>Weight</th><th>Note</th></tr>"
        f"<tr><td>{criterion}</td><td>80%</td><td>Example note</td></tr></table>"
    )


class RubricGenerationTests(unittest.TestCase):
    def test_version_gaps_and_new_criteria(self):
        pages = {"1.0": page("1.0"), "2.5": page("2.5", "Battery Longevity"), "3.0": page("3.0")}
        client = Mock()
        client.get_wiki_page_html.side_effect = lambda title: pages.get(title.split("_v")[-1], "<h1>Not found</h1>")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rubric.json"
            generate_rubric_json(client, str(output))
            data = json.loads(output.read_text())
        self.assertEqual(data["versions"], ["1.0", "2.5", "3.0"])
        for criterion in data["criteria"]:
            self.assertEqual(len(criterion["included"]), len(data["versions"]))
        new = next(c for c in data["criteria"] if c["name"] == "Battery Longevity")
        self.assertEqual(new["included"], [False, True, False])
        self.assertEqual(new["weights"], {"2.5": "80%"})
        self.assertEqual([item["version"] for item in data["revisions"]], data["versions"])

    def test_missing_previous_version_keeps_output(self):
        client = Mock()
        client.get_wiki_page_html.return_value = "<h1>Not found</h1>"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rubric.json"
            original = json.dumps({"versions": ["2.4"]})
            output.write_text(original)
            with self.assertRaises(ValueError):
                generate_rubric_json(client, str(output))
            self.assertEqual(output.read_text(), original)

    def test_changed_source_markup_keeps_output(self):
        client = Mock()
        client.get_wiki_page_html.return_value = "<h1>Repairability Scoring Rubric v1.0</h1><p>New layout</p>"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rubric.json"
            with self.assertRaisesRegex(ValueError, "scoring table"):
                generate_rubric_json(client, str(output))
            self.assertFalse(output.exists())

    def test_changed_column_order_fails(self):
        client = Mock()
        client.get_wiki_page_html.return_value = page("1.0").replace(
            "<th>Weight</th><th>Note</th>", "<th>Note</th><th>Weight</th>"
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "columns changed"):
            generate_rubric_json(client, str(Path(directory) / "rubric.json"))

    def test_partial_fetch_cannot_remove_existing_version(self):
        client = Mock()
        client.get_wiki_page_html.side_effect = lambda title: (
            page("1.0") if title.endswith("v1.0") else "<h1>Not found</h1>"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rubric.json"
            original = json.dumps({"versions": ["1.0", "2.4"]})
            output.write_text(original)
            with self.assertRaisesRegex(ValueError, "Previously published"):
                generate_rubric_json(client, str(output))
            self.assertEqual(output.read_text(), original)

    def test_revision_topics_and_rule_changes_are_preserved(self):
        client = Mock()
        html = page("2.4") + (
            "<p>Revisions From Previous Version</p><table>"
            "<tr><td>Tools</td><td>Adjusted multipliers for combination tools</td></tr>"
            "<tr><td>Proxy Times</td><td>Adjusted thermal compound removal times</td></tr></table>"
        )
        client.get_wiki_page_html.side_effect = lambda title: html if title.endswith("v2.4") else "<h1>Not found</h1>"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rubric.json"
            generate_rubric_json(client, str(output))
            data = json.loads(output.read_text())
        self.assertEqual(
            data["revisions"],
            [
                {
                    "version": "2.4",
                    "items": [
                        "Tools: Adjusted multipliers for combination tools",
                        "Proxy Times: Adjusted thermal compound removal times",
                    ],
                }
            ],
        )
