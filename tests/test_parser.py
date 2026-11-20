import unittest

from apexprime.utils import extract_json_object


class ParserTests(unittest.TestCase):
    def test_extracts_apex_table_with_surrounding_text(self):
        raw = '''Análise objetiva.\n[APEX_TABLE]\n{"signal":"NO_TRADE","direction":"NONE"}\n[/APEX_TABLE]'''
        parsed = extract_json_object(raw)
        self.assertEqual(parsed["signal"], "NO_TRADE")

    def test_rejects_incomplete_json(self):
        with self.assertRaises(ValueError):
            extract_json_object('[APEX_TABLE]{"signal":"LONG"[/APEX_TABLE]')


if __name__ == "__main__":
    unittest.main()
