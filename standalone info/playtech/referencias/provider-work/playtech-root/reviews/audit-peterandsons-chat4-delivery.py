"""Independent read-only inspection of Chat4 delivery. Writes only ROOT review."""
import collections,hashlib,json,sys,time
from decimal import Decimal
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'provider-work/peterandsons-chat4'
sys.path.insert(0,str(B/'code'))
from protocol import audit_round,minimum_modes,settlement_rejected
read=lambda p:json.loads(p.read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':p.relative_to(R).as_posix(),'sha256':sha(p)}
report=read(B/'results/provider-report.json');final=read(B/'results/final-audit.json');catalogue=read(B/'results/catalogue.json')
assert len(catalogue)==len({x['game_id']for x in catalogue})==len(report['games'])==75
assert {g['id']for g in report['games']}=={g['game_id']for g in catalogue}
issues=[];audited=[];holds=[];pending=[];references=0;steps=0;ids=set()
for g in report['games']:
 plan=read(B/f"private/plans/{g['id']}.json");assert plan['modes']==minimum_modes(plan['info'])
 for m in g['modes']:
  for v in m.get('evidence',[]):
   p=(B/v['path']).resolve();assert p.is_relative_to(B.resolve())and sha(p)==v['sha256'];references+=1
  if m['status']=='pending':pending.append({'game':g['id'],'mode':m['id']});continue
  conditional='::offer::'in m['id']
  p=B/f"private/conditional-cases/{m['id'].split('::offer::')[1]}.json"if conditional else B/f"private/rounds/{g['id']}--{m['id']}.json"
  row=read(p);folder=B/'private/sessions'/row['session'];journals=[read(x)for x in folder.glob('*.json')if x.name!='credentials.json']
  info=read(folder/'information.json')['response'];play=[x for x in journals if x.get('path')=='/game/play'and x.get('request')==row['play_request']and x.get('response')==row['play_response']];assert len(play)==1 and play[0]['http_status']==200
  rounds=[x for x in journals if x.get('path')=='/game/complete'and x.get('request',{}).get('roundId')==row['play_response']['roundId']];assert len(rounds)==1
  end=rounds[0]
  if m['status']=='needs_review':
   assert row['status']!='verified'and settlement_rejected(row['play_response'],end)
   holds.append({'game':g['id'],'mode':m['id'],'error':end['response']['error']['code'],'hold':ref(B/f"private/holds/{g['id']}.json")});continue
  assert m['status']=='verified_remote'and row['status']=='verified'and end['http_status']==200
  assert end['request']==row['complete_request']and end['response']==row['complete_response']
  for c in row.get('continuations',[]):assert len([x for x in journals if x.get('path')=='/game/play'and x.get('request')==c['request']and x.get('response')==c['response']and x.get('http_status')==200])==1
  auth=read(folder/'authentication.json')['response'];prior=[x for x in journals if x.get('path')=='/game/complete'and x.get('http_status')==200 and x['started_at']<play[0]['started_at']]
  before=max(prior,key=lambda x:x['started_at'])['response']['balance']if prior else auth['balance'];assert Decimal(str(before))==Decimal(str(row['balance_before']))
  audit=audit_round(before,info,row['play_request'],row['play_response'],end['request'],end['response'],row.get('continuations'));assert audit==row['audit']
  # Independent decimal wallet identity in addition to the provider's stored audit.
  cost=Decimal(str(row['play_request']['bet']))+sum((Decimal(str(c['request'].get('bet',0)))for c in row.get('continuations',[])),Decimal(0))
  win=sum((Decimal(str(v['wager']['win']))for v in [row['play_response']]+[c['response']for c in row.get('continuations',[])]),Decimal(0))
  assert Decimal(str(before))-cost+win==Decimal(str(end['response']['balance']))and win==Decimal(str(end['response']['finalWin']))
  identity=(row['session'],row['play_response']['roundId']);assert identity not in ids;ids.add(identity)
  if not conditional:assert {'id':m['id'],'kind':m['kind'],'bet':m['bet']}in minimum_modes(info)
  audited.append({'game':g['id'],'mode':m['id'],'kind':m['kind'],'conditional':conditional,'result':audit});steps+=audit['internal_steps']
assert len(audited)==239 and steps==1870 and len(holds)==5 and len(pending)==3
assert final['summary']==report['summary']and len(final['verified_rounds'])==239
assert sum(g['status']=='complete'for g in report['games'])==70
assert all(g['status']!='complete'or all(m['status']=='verified_remote'for m in g['modes'])for g in report['games'])
mode_kinds=collections.Counter(x['kind']for x in audited)
# Distinct replication: confirm seven records without counting them as new catalogue modes.
seq=read(B/'private/replications/inks-pints-sequence.json');assert seq['status']=='verified'and len(seq['rounds'])==7
folder=B/'private/sessions'/seq['session'];info=read(folder/'information.json')['response'];balance=read(folder/'authentication.json')['response']['balance'];cost=Decimal(0);payout=Decimal(0)
for row in seq['rounds']:
 n=row['index'];play=read(folder/f'{n:02d}-play.json');end=read(folder/f'{n:02d}-complete.json');assert play['http_status']==end['http_status']==200
 assert play['request']==row['play_request']and play['response']==row['play_response']and end['request']==row['complete_request']and end['response']==row['complete_response']
 a=audit_round(balance,info,play['request'],play['response'],end['request'],end['response']);assert a==row['audit'];balance=end['response']['balance'];cost+=Decimal(str(a['cost']));payout+=Decimal(str(a['payout']))
assert balance==seq['balance_after']==9969 and cost==312 and payout==281
# Frozen exports are assessed against their own pinned contents, not a later source edit.
bundles=[];secrets=[str(v).encode()for p in (B/'private/sessions').glob('*/credentials.json')for k,v in read(p).items()if k in ('key','token')and v]
for dirname in ['peterandsons-evidence','peterandsons-evidence-bloody-update','inks-pints-har-addendum','inks-pints-replication']:
 folder=B/'export'/dirname;mp=folder/'manifest.json';manifest=read(mp)
 for e in manifest['files']:
  p=(folder/e['path']).resolve();assert p.is_relative_to(folder.resolve())and p.name!='credentials.json'and p.suffix.lower()!='.har';data=p.read_bytes();assert hashlib.sha256(data).hexdigest()==e['sha256'];assert not any(secret in data for secret in secrets)
 bundles.append({'manifest':ref(mp),'files':len(manifest['files']),'hashes_passed':True,'known_session_credentials_absent':True})
old=read(B/'export/peterandsons-evidence/manifest.json');oldhold=next(e for e in old['files']if e['path']=='private/holds/inks-pints.json');assert sha(B/oldhold['path'])==oldhold['sha256']
out={'schema':'root-peterandsons-chat4-delivery-review/v1','updated_at':time.time(),'thread_title':'Crear un relay proxy (4)','status':'accepted_scoped_partial_delivery','catalogue_games':75,'games_complete_for_identified_minimum_modes':70,'games_with_unreconciled_prior_settlement':5,'verified_modes':239,'mode_kinds':dict(mode_kinds),'internal_steps':steps,'conditional_purchases_verified':2,'mode_evidence_references_checked':references,'pending_not_started':pending,'held_original_settlements':holds,'replication_additional_not_new_mode_coverage':{'game':'inks-pints','verified_rounds':7,'cost':312,'payout':281,'balance_before':10000,'balance_after':9969,'old_hold_unchanged':True},'bundles':bundles,'issues':issues,'coverage_limits':['Identified native minimum modes only; not all stakes/line permutations.','Original five rejected settlements remain unresolved. A different session cannot reconcile them.','Inks additional successful Jackpot proves operation at tested amount/timing; no causal diagnosis of prior rejection.','Captured HAR cycles, parent preparations, conditional modes and seven additional replication rounds are separate counts.'],'source_report':ref(B/'results/provider-report.json'),'source_audit':ref(B/'results/final-audit.json'),'network_requests':0,'new_game_outcomes':0,'other_chat_files_modified':False}
target=Path(__file__).with_name('peterandsons-chat4-delivery-root-review.json');target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print(json.dumps({'verified_modes':239,'mode_kinds':dict(mode_kinds),'steps':steps,'references':references,'bundles':[(x['files'])for x in bundles],'pending':pending,'held_games':[x['game']for x in holds],'report':target.relative_to(R).as_posix()}))
