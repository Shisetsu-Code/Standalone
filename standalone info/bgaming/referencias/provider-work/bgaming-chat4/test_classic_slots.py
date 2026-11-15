import unittest
from classic_slots import metadata
class ClassicSlots(unittest.TestCase):
 def source(self):return 'My.games.WestTown={init:iB};for(let r in A.config.bet)n[r]=Math.round(A.config.bet[r]*A.config.subunits);t.options={bets:n},t.command="spin";let r=n.result&&n.result.total?n.result.total:0;J.request({command:"finish"},callback);'
 def test_explicit_game_and_native_indexed_wire_required(self):
  m=metadata(self.source(),'WestTown');self.assertTrue(m['v1_result_total_verified']);self.assertEqual(m['client_family'],'classic-casino')
  with self.assertRaises(ValueError):metadata(self.source(),'UnregisteredGame')
  with self.assertRaises(ValueError):metadata(self.source().replace('A.config.subunits','unknownFactor'),'WestTown')
