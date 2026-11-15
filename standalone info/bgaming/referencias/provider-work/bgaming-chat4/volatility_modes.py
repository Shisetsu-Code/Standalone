"""Source-defined paid base volatility, removed before the purchased free-spin round."""
import re,copy,hashlib
from native_variants import balanced
def metadata(source):
 selector=re.search(r'additionalSpinOptions\.volatility=1==this\.getCurrentVolatility\(\)\?"([a-z]+)":"([a-z]+)"',source);methods=list(re.finditer(r'beforeGoFreespins\([^)]*\)\{',source));proved=False
 for method in methods:
  body=balanced(source,method.end()-1)
  if 'delete this.additionalSpinOptions.volatility' in body and 'this.fsModeSwitcher(Number(' in body:proved=True
 if not selector or selector.groups()!=('low','medium') or not proved:raise ValueError('Paid volatility values/free-spin deletion not proved')
 return dict(paid_volatility_values=list(selector.groups()),volatility_removed_before_freespins=True,continuation_whitelist=['freespin'],volatility_source_sha256=hashlib.sha256(source.encode()).hexdigest(),volatility_evidence='Boolean base selector sends low/medium on paid spins. Buy level is a separate native selector; beforeGoFreespins uses its confirmed level and deletes volatility before free spins. Paid base value and resulting bonus type must not be conflated.')
def plan(initial,meta):
 from run_demo_qa import modes_from_init
 plain=dict(meta);plain.pop('paid_volatility_values');base=modes_from_init(copy.deepcopy(initial),plain);result=[]
 for value in meta['paid_volatility_values']:
  for mode in base:
   m=copy.deepcopy(mode);m['name']+='@base_volatility:'+value;m['options']['volatility']=value;m['volatility_lifecycle']='paid request only; omitted before freespins';result.append(m)
 return result
