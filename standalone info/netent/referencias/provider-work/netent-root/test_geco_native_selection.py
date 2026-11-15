import unittest
from geco_native_selection import character_parameters

class CharacterTests(unittest.TestCase):
    def test_opponent_comes_from_current_session_order_excluding_character(self):
        self.assertEqual(character_parameters({'spinInfo.randomOpponents':'RYU,DHALSIM,KEN'},'RYU'),{'character':'RYU','opponent':'DHALSIM'})
        self.assertEqual(character_parameters({'spinInfo.randomOpponents':'BLANKA,RYU,KEN'},'RYU'),{'character':'RYU','opponent':'BLANKA'})
    def test_unoffered_or_unplayable_choices_are_not_invented(self):
        with self.assertRaises(ValueError):character_parameters({'spinInfo.randomOpponents':'RYU'},'RYU')
        with self.assertRaises(ValueError):character_parameters({'spinInfo.randomOpponents':'RYU,KEN'},'MBISON')
