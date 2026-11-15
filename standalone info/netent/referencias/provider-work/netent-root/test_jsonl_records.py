import unittest
from jsonl_records import parse_jsonl

class JsonlTests(unittest.TestCase):
    def test_unicode_line_separators_inside_valid_json_are_not_record_boundaries(self):
        self.assertEqual(parse_jsonl('{"text":"a\u0085b\u2028c"}\n{"ok":true}\n'),[{'text':'a\u0085b\u2028c'},{'ok':True}])
    def test_invalid_json_remains_an_error(self):
        with self.assertRaises(ValueError):parse_jsonl('{"unfinished":\n')
