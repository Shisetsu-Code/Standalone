import unittest
from native_decisions import jungle_choice

class DecisionTests(unittest.TestCase):
    def test_animal_type_and_native_boolean_payload_are_preserved(self):
        profile={'animal':'3','gamble':True}
        self.assertEqual(jungle_choice(profile,{'featuredAnimal':None},[]),{'featureBuy':False,'animal':'3'})
        self.assertEqual(jungle_choice(profile,{'featuredAnimal':{'id':3}},[]),{'featureBuy':False,'gamble':True})
        self.assertEqual(jungle_choice(profile,{'featuredAnimal':{'id':3}},[{'gamble':True}]),{'featureBuy':False,'gamble':False})
        with self.assertRaises(ValueError):jungle_choice({'animal':'99','gamble':False},{},[])
