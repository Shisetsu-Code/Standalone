import unittest,json
from pathlib import Path
from line_count_modes import metadata,plan
class LineCounts(unittest.TestCase):
 def test_hidden_unsupported_line_buttons_are_not_executed(self):
  source='var choices=["20","40","60","80","100"],F={20:1,60:3,100:5};onLinesCountChanged(e){this.linesCount=e,this.additionalSpinOptions.mode=this.linesCount,this.setBetsVisibleMultiplier(F[e],!0)}'
  hidden=''.join('name:"line-select-item-'+x+'",x:0},":":[{c:"Button",p:{name:"button",alpha:0,visible:!1,interactive:!1,onClick:"currentScene.selectItem`'+x+'"}}]' for x in ['40','80'])
  self.assertEqual(metadata(source+hidden)['line_count_disabled_controls'],['40','80'])
  with self.assertRaises(ValueError):metadata(source+hidden.replace('interactive:!1','interactive:!0'))
 def test_fishing_contract_is_explicitly_supported(self):
  from unittest.mock import patch
  from legacy_metadata import prove_line_counts
  source='var choices=["20","40","60","80","100"],F={20:1,40:2,60:3,80:4,100:5};onLinesCountChanged(e){this.linesCount=e,this.additionalSpinOptions.mode=this.linesCount,this.setBetsVisibleMultiplier(F[e],!0)}'
  with patch('legacy_metadata.load_client',return_value=({},source)),patch('legacy_metadata.save'):
   self.assertEqual(prove_line_counts('FishingClub',None)['line_count_modes']['100'],5)
 def test_wire_line_count_strings_are_distinct_from_price_factors(self):
  source='var choices=["20","40","60","80","100"],F={20:1,40:2,60:3,80:4,100:5};onLinesCountChanged(e){this.linesCount=e,this.additionalSpinOptions.mode=this.linesCount,this.setBetsVisibleMultiplier(F[e],!0)}'
  meta=metadata(source);self.assertEqual(meta['line_count_modes'],{'20':1,'40':2,'60':3,'80':4,'100':5})
  with self.assertRaises(ValueError):metadata(source.replace('this.additionalSpinOptions.mode=this.linesCount','unknown()'))
 def test_five_minimum_native_line_modes(self):
  a=json.loads((Path(__file__).parent/'live/WildTiger.json').read_text(encoding='utf8'))['events'][0]['response'];m=plan(a,{'line_count_modes':{'20':1,'40':2,'60':3,'80':4,'100':5}});self.assertEqual([x['options']['mode'] for x in m],['20','40','60','80','100']);self.assertEqual([x['options']['bet'] for x in m],[20]*5);self.assertEqual([x['cost_native'] for x in m],[20,40,60,80,100]);self.assertTrue(all(x['continuation_options']=={'mode':x['options']['mode']} for x in m))
