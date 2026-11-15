import unittest
from progression_history import archive_verified_duplicates


class ProgressionHistoryTests(unittest.TestCase):
    def test_repeat_rounds_preserve_their_ledger_without_inflating_unique_modes(self):
        first={'mode':'FeatureBuy:select=randomwilds','state':'verified','passed':True,'cost':'5','win':'1'}
        second={**first,'win':'2'}
        pending={**first,'state':'sent_or_uncertain','passed':False}
        proof={'cases':[first,second,pending]}
        archive_verified_duplicates(proof)
        self.assertEqual(proof['cases'],[first,pending])
        self.assertEqual(proof['progression_rounds'],[second])
        archive_verified_duplicates(proof)
        self.assertEqual(len(proof['progression_rounds']),1)
