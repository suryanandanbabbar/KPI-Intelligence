"""
KPI Intelligence — JSONC Parser Unit Tests.
"""

import unittest
import json
from backend.connectors.powerbi.jsonc_parser import parse_jsonc, strip_jsonc_comments_and_trailing_commas


class TestJsoncParser(unittest.TestCase):

    def test_standard_json(self):
        raw = '{"name": "test", "value": 42, "flag": true, "list": [1, 2, 3]}'
        res = parse_jsonc(raw)
        self.assertEqual(res["name"], "test")
        self.assertEqual(res["value"], 42)
        self.assertEqual(res["flag"], True)
        self.assertEqual(res["list"], [1, 2, 3])

    def test_single_line_comments(self):
        raw = """
        {
            // This is a comment at top
            "name": "Power BI", // Inline comment
            "version": "1.0"
            // Another comment
        }
        """
        res = parse_jsonc(raw)
        self.assertEqual(res["name"], "Power BI")
        self.assertEqual(res["version"], "1.0")

    def test_multi_line_comments(self):
        raw = """
        {
            /*
             * Multi-line block comment
             */
            "dataset": "Sales",
            /* inline block */ "enabled": false
        }
        """
        res = parse_jsonc(raw)
        self.assertEqual(res["dataset"], "Sales")
        self.assertFalse(res["enabled"])

    def test_comments_inside_strings_preserved(self):
        raw = r'''
        {
            "url": "http://api.powerbi.com/v1.0/myorg//reports",
            "escaped": "String with \"//not a comment\" and /*not a block*/",
            "regex": "^[a-z]+//[0-9]+$"
        }
        '''
        res = parse_jsonc(raw)
        self.assertEqual(res["url"], "http://api.powerbi.com/v1.0/myorg//reports")
        self.assertEqual(res["escaped"], 'String with "//not a comment" and /*not a block*/')
        self.assertEqual(res["regex"], "^[a-z]+//[0-9]+$")

    def test_trailing_commas_in_objects_and_arrays(self):
        raw = """
        {
            "items": [
                1,
                2,
                3,
            ],
            "nested": {
                "a": 10,
                "b": 20,
            },
        }
        """
        res = parse_jsonc(raw)
        self.assertEqual(res["items"], [1, 2, 3])
        self.assertEqual(res["nested"], {"a": 10, "b": 20})

    def test_empty_content(self):
        self.assertEqual(parse_jsonc(""), {})
        self.assertEqual(parse_jsonc("   \n\t  "), {})

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_jsonc('{"invalid": [1, 2')


if __name__ == "__main__":
    unittest.main()
