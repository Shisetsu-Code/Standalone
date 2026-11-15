"""Literal UI paid activators, distinct from unused internal purchase price entries."""
import re,hashlib,copy
def metadata(source):
 controls=sorted(set(re.findall(r'onClick:"all\.buy-bonus\.switchChance`([^"`]+)"',source)))
 needles=['setBoughtBonusParameter(i?t:null,e)','switchChance(t){if(!this.isFeaturesDisabled(!1,"buy_chance"))','bonusPrice(t){return Math.floor(o.A.currentScene.getBet()*this.chanceMultipliers[t])}', 'this.baseChancePrices[r]=a/n','Object.keys(this.isChanceSwitchedOn).forEach((e=>{this.isChanceSwitchedOn[e]&&e!==t&&"bonus_buy"!==e']
 if controls!=['bonus_buy_0_chance','bonus_buy_1_chance'] or any(n not in source for n in needles) or re.search(r'onClick:"[^"\n]*buyBonusClick',source):raise ValueError('Lucky Dragon literal controls/source contract differs')
 return dict(lucky_dragon_controls_verified=True,source_sha256=hashlib.sha256(source.encode()).hexdigest(),paid_ui_controls=controls,evidence=[dict(offset=source.index(n),excerpt=n) for n in needles],price_registry_not_exposed=['bonus_buy:bonus_buy_0','bonus_buy:bonus_buy_1'],note='This version exposes two mutually exclusive paid chance switches; internal bonus_buy price entries have no UI purchase control. Prior rejected generic purchase stays in evidence.')
def plan(initial,meta):
 if not meta.get('lucky_dragon_controls_verified') or initial['options']['currency']!={'code':'FUN','symbol':'FUN','subunits':100}:
  currency=initial['options']['currency']
  if not meta.get('lucky_dragon_controls_verified') or currency.get('code')!='FUN' or currency.get('subunits')!=100:raise ValueError('Verified native FUN controls required')
 o=initial['options'];bet=min(o['available_bets']);fm=o['feature_options']['feature_multipliers'];base=fm['base_bet'];disabled=o['feature_options'].get('disabled_features',[])
 result=[dict(name='normal',command='spin',options={'bet':bet},cost_native=bet)]
 for feature in meta['paid_ui_controls']:
  if feature in disabled:continue
  numerator=bet*fm[feature];cost,remainder=divmod(numerator,base)
  if remainder:raise ValueError('Nonintegral native chance cost')
  result.append(dict(name=feature,command='spin',options=dict(bet=bet,purchased_feature=feature),cost_native=cost))
 return result
