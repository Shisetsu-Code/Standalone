"""Observed SlotKit-style JSON-RPC product IDs and whole-round response format."""
import re,json,hashlib
from fractions import Fraction
from native_variants import balanced,fields

def metadata(source,allowed):
 wires=re.findall(r'const [A-Za-z_$][\w$]*=\{bet:[A-Za-z_$][\w$]*,purchased_feature:[A-Za-z_$][\w$]*,(buy_id|bonus_buy):[A-Za-z_$][\w$]*\}',source)
 if len(set(wires))!=1 or not any(token in source for token in ['this._getPlayResponse(null)','this._getPlayResponse()']):raise ValueError('Product-round request/continuation source not recognized')
 wire_field=wires[0]
 arrays=[]
 for m in re.finditer(r'function [A-Za-z_$][\w$]*\(\)\{return\[',source):
  value=balanced(source,m.end()-1,'[',']')
  if 'purchaseFeature:' in value and 'price:' in value:arrays.append(value)
 if len(arrays)!=1:raise ValueError('Product list not uniquely recognized')
 def literal(value):
  try:return json.loads(value)
  except ValueError:pass
  if value in ('!0','!1'):return value=='!0'
  if not re.fullmatch('[A-Za-z_$][\w$]*',value):raise ValueError('Nonliteral product field')
  values=set(re.findall(r'(?<![\w$])'+re.escape(value)+r'=("[^"\\]*"|\d+(?:\.\d+)?)(?=[,;])',source))
  if len(values)!=1:raise ValueError('Ambiguous product constant')
  return json.loads(values.pop())
 array=arrays[0];products=[];pos=1
 while pos<len(array)-1:
  while array[pos] in ' ,\n\r\t':pos+=1
  if array[pos]!='{':raise ValueError('Computed product list needs review')
  obj=balanced(array,pos);pos+=len(obj);f=fields(obj)
  product=dict(id=literal(f['id']),factor=str(literal(f['price'])),feature=literal(f['purchaseFeature']),activation=literal(f.get('activation','false')),hidden=literal(f.get('hidden','false')))
  if product['feature'] not in allowed:continue
  if Fraction(product['factor'])<=0:raise ValueError('Invalid product price')
  products.append(product)
 return dict(engine='product-round',protocol='jsonrpc-product-round',product_wire_id_field=wire_field,products=products,unresolved=[],source_sha256=hashlib.sha256(source.encode()).hexdigest(),evidence='Official product registry id/price/purchaseFeature; explicit native product ID field '+wire_field+'; continuation without another product selection',hidden_product_policy='Registry products are retained with their hidden flag; UI visibility is not certified by API QA')

def plan(initial,meta):
 r=initial['result'];a=r['currency_attributes']
 if r['currency']!='FUN' or a['subunits']!=100 or a['exponent']!=2 or r.get('freebets') or r.get('state') is not None:raise ValueError('Unverified product-round initial state')
 bet=min(r['config']['bet_limits']);modes=[]
 for product in [dict(id=None,feature=None,factor='1')]+meta['products']:
  cost=bet*Fraction(product['factor'])
  if cost.denominator!=1:raise ValueError('Fractional product price')
  modes.append(dict(name=product['id'] or 'normal',protocol='jsonrpc-product-round',product_id=product['id'],product_wire_id_field=meta.get('product_wire_id_field','buy_id'),feature=product['feature'],bet_native=bet,cost_native=int(cost),hidden_registry_product=product.get('hidden',False)))
 return modes

def run(h,mode):
 if h.last.get('final') is False or (h.last.get('state') is not None and 'final' not in h.last):raise RuntimeError('Product round already open')
 before=Fraction(str(h.last['balance']));cost=mode['cost_native'];bet=mode['bet_native'];start=len(h.parent.events)
 if before<cost:return dict(mode=mode,status='insufficient_demo_balance')
 req={'bet':bet}
 if mode['product_id'] is not None:req.update({mode.get('product_wire_id_field','buy_id'):mode['product_id'],'purchased_feature':mode['feature']})
 r=h.request('play',req)['result']
 for _ in range(500):
  if not isinstance(r.get('final'),bool):raise RuntimeError('Product final flag missing; no continuation sent')
  if not isinstance(r.get('resp',{}).get('round'),dict):raise RuntimeError('Product round response schema changed')
  if r.get('final') is True:break
  r=h.request('play',{'bet':bet})['result']
 else:raise RuntimeError('Product round continuation limit')
 round_data=r['resp']['round'];win=Fraction(str(round_data['win']));expected=before-cost+win;actual=r['balance'];ok=expected==Fraction(str(actual));h.parent.money_checks.append(dict(kind='round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=actual,ok=ok))
 if not ok:raise RuntimeError('Product whole-round wallet rule needs review; no next round sent')
 return dict(mode=mode,status='closed',first_event=start,last_event=len(h.parent.events)-1,final_balance=actual,final_state='final',win_ratio=[win.numerator,win.denominator],win_native=int(win) if win.denominator==1 else float(win))

def audit(initial,events,meta):
 balance=Fraction(str(initial['result']['balance']));prices={p['id']:Fraction(p['factor']) for p in meta['products']};checks=[];rounds=[];current=None
 for index,event in enumerate(events):
  if event['request'].get('method')!='play':continue
  response=event.get('response',{})
  if 'result' not in response:checks.append(dict(event=index,kind='rpc_result',ok=False));continue
  result=response['result'];req=event['request']['params']['req']
  if current is None:
   product=req.get(meta.get('product_wire_id_field','buy_id'));cost=Fraction(str(req['bet']))*(prices[product] if product is not None else 1);current=dict(start_event=index,before_ratio=[balance.numerator,balance.denominator],cost_ratio=[cost.numerator,cost.denominator],buy_id=product,product_wire_id_field=meta.get('product_wire_id_field','buy_id'),closed=False);rounds.append(current)
  if result.get('final') is True:
   win=Fraction(str(result['resp']['round']['win']));before=Fraction(*current['before_ratio']);cost=Fraction(*current['cost_ratio']);actual=Fraction(str(result['balance']));expected=before-cost+win;checks.append(dict(event=index,kind='round_balance',expected_ratio=[expected.numerator,expected.denominator],actual_native=result['balance'],ok=expected==actual));current.update(closed=True,end_event=index,final_balance_native=result['balance'],win_ratio=[win.numerator,win.denominator]);balance=actual;current=None
 return checks,rounds
