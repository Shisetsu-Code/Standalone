"""Legacy check_card choices parsed from the official game UI and exact request envelope."""
import re,hashlib
def metadata(source):
 if not re.search(r'command:[A-Za-z_$][\w$]*\.isApi2\?"gamble":"check_card",options:\{bet:[A-Za-z_$][\w$]*,additionalInfo:[A-Za-z_$][\w$]*\}',source):raise ValueError('Native check_card envelope not proved')
 choices=list(dict.fromkeys(re.findall(r'onClick:"currentScene\.playGamble`([a-z]+)"',source)))
 if set(choices)!={'s','c','d','h','black','red'} or not re.search(r'\.gamble\([A-Za-z_$][\w$]*\)\.then\(',source):raise ValueError('Gamble UI choice set not explicit')
 return dict(classic_gamble_verified=True,classic_gamble_choices=choices,classic_gamble_source_sha256=hashlib.sha256(source.encode()).hexdigest(),classic_gamble_evidence='Six literal UI callbacks feed playGamble -> API.gamble(choice), sending check_card/options.bet as the choice string. additionalInfo is undefined and omitted by JSON.stringify; no monetary amount is substituted for that semantic field.')

def check_event(before,event,meta):
 request=event['request'];response=event['response'];choice=request.get('options',{}).get('bet')
 if not meta.get('classic_gamble_verified') or request.get('command')!='check_card' or choice not in meta['classic_gamble_choices'] or 'check_card' not in before.get('available_commands',[]):raise ValueError('Gamble choice/envelope not source verified or currently advertised')
 game=response.get('game',{}).get('bonus_game',{});result=response.get('result');missing_loss=result is None and game.get('result')=='lose' and meta.get('v1_result_total_verified');stake=before.get('bets',{}).get('required_for_bonus_game');payout=0 if missing_loss else (result or {}).get('bonus_game');actual=response.get('balance');old=before.get('balance')
 if any(type(v) is not int for v in [stake,payout,actual,old]) or stake<=0 or payout<0:raise ValueError('Unverified classic gamble native amounts')
 if response.get('bets',{}).get('bonus_game')!=stake or (not missing_loss and (result or {}).get('total')!=payout) or game.get('bet')!=choice or game.get('result') not in ['win','lose']:raise ValueError('Gamble response does not confirm native choice/stake/payout')
 expected=old-stake+payout
 if expected!=actual:raise ValueError('Classic gamble native wallet mismatch')
 return dict(kind='classic_gamble_native_balance',choice=choice,stake_native=stake,payout_native=payout,expected=expected,actual=actual,ok=True)

def check_finish(before,response,meta):
 if not meta.get('finish_command_verified') or 'finish' not in before.get('available_commands',[]) or response.get('game',{}).get('state')!='closed':raise ValueError('Source-verified finish not available/closed')
 expected=before['balance'];actual=response.get('balance')
 if actual!=expected:raise ValueError('Finish unexpectedly changed already credited native balance')
 return dict(kind='classic_finish_native_balance',expected=expected,actual=actual,ok=True)
