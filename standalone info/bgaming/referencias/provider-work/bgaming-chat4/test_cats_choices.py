import unittest
from cats_choices import metadata,next_choice
class CatsChoices(unittest.TestCase):
 def test_source_proves_index_envelope_and_six_button_positions(self):
  s='var i=t.parent.parent.children.indexOf(t.parent);qt.request({command:"play_bonus",options:{index:i}});'
  s+='{c:"MovieClip",p:{name:"bottles"},":":['+','.join('{c:"MovieClip",p:{name:"jar"}}' for _ in range(6))+']}'
  self.assertEqual(metadata(s)['cats_bottle_count'],6)
  with self.assertRaises(ValueError):metadata(s.replace('options:{index:i}','options:{}'))
 def test_choose_only_unopened_native_positions(self):
  r={'flow':{'state':'play_bonus','available_actions':['init','play_bonus']},'features':{'bonus_data':{'prizes_data':{'all':[{'index':0},{'index':2}]}}}}
  self.assertEqual(next_choice(r,{'cats_bottle_count':6}),{'index':1})
  r['features']['bonus_data']['prizes_data']['all'].append({'index':8})
  with self.assertRaises(ValueError):next_choice(r,{'cats_bottle_count':6})
