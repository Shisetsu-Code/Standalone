"""Read-only Playson report builder; raw XML/authentication stays private."""
import json,sys,re,hashlib,shutil
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent.parent;OUT=ROOT/'provider-work/playson-root'
sys.path.insert(0,str(ROOT/'demo-dashboard'))
import external_provider_reports as common

def catalog_metadata(catalog, source):
 if not catalog.get('catalog_complete'):return {'catalog_complete':False,'full_catalog_total':None,'catalog_scope':'Partial catalogue; pagination end not independently confirmed','upcoming':catalog.get('upcoming',[])}
 pages=catalog.get('pages',[]);games=catalog['games'];total=catalog.get('full_catalog_total')
 if not pages or pages[-1].get('next_url') or not catalog.get('pagination_terminal_confirmed'):raise ValueError('Catalogue terminal page not confirmed')
 if total!=len(games)or len({g.get('official_slug',g['slug'])for g in games})!=total:raise ValueError('Catalogue total or identities inconsistent')
 folder=(source/catalog['snapshot_path']).resolve()
 if not folder.is_relative_to(source.resolve()):raise ValueError('Catalogue snapshot outside source')
 official=[]
 for i,page in enumerate(pages):
  path=(folder/page['file']).resolve()
  if not path.is_relative_to(folder):raise ValueError('Catalogue page outside snapshot')
  if not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=page['sha256']:raise ValueError('Missing or changed catalogue page')
  captured=json.loads(path.read_text(encoding='utf8'))
  if captured['url']!=page['url']or captured['next_url']!=page['next_url']or len(captured['games'])!=page['game_count']:raise ValueError('Catalogue page metadata inconsistent')
  if i+1<len(pages)and page['next_url']!=pages[i+1]['url']:raise ValueError('Catalogue pagination gap')
  official.extend(r['slug']for r in captured['games'])
 if official!=[g.get('official_slug',g['slug'])for g in games]:raise ValueError('Catalogue rows differ from archived pages')
 return {'catalog_complete':True,'full_catalog_total':total,'catalog_scope':'Complete published official website catalogue; all pagination archived','catalog_pages_saved':len(pages),'catalog_captured_at':catalog['captured_at'],'upcoming':catalog.get('upcoming',[])}

def build(source=OUT):
 catalog_path=source/('catalog-current.json'if(source/'catalog-current.json').exists()else'catalog-captured.json');catalog=json.loads(catalog_path.read_text(encoding='utf8'));reference=json.loads((source/'har-reference.json').read_text(encoding='utf8'));byref={g['game_id']:g for g in reference['games']};games=[];resolution=json.loads((source/'launch-resolution.json').read_text(encoding='utf8'))if(source/'launch-resolution.json').exists()else{}
 for row in catalog['games']:
  g={'game_id':row['slug'],'title':row['title'],'game_type':'Slots','status':'pending_official_launch','complete':False,'declared_modes':0,'modes':[],'historical_failed_checks':0,'har_reference_rounds':len(byref.get(row['slug'],{}).get('rounds',[])),'locked_options':[],'pending_reason':'En cola de pruebas HTTP'if row['slug']in resolution else'Identificador interno de demo pendiente de resolver'}
  p=source/'live/games'/(row['slug']+'.json')
  if p.exists():
   proof=json.loads(p.read_text(encoding='utf8'));g['declared_modes']=len(proof['mode_cost_factors']);g['native_client_sha256']=proof.get('native_client_sha256');g['native_minimum_minor']=proof.get('minimum_base_minor')
   for c in proof['cases']:
    checks=c.get('checks',{});passed=bool(c.get('passed'))and bool(checks)and all(checks.values());g['modes'].append({'name':c['mode'],'mode':c['mode'],'kind':'normal'if c['mode']=='Spin'else'special','state':c['state'],'status':'verified'if passed else'failed_validation'if c.get('validation_concluded')else'needs_review','validation_concluded':c.get('validation_concluded',False),'complete':passed,'checks':checks,'steps':[{k:step[k]for k in ['kind','command','status','state','credit_minor','base_win_minor','bonus_win_minor','bonus_spins_left','free_win_minor','free_spins_remaining','native_cash_bet_minor','bonus_present']if k in step}for step in c.get('steps',[])],**{k:c[k]for k in ['before_minor','after_minor','cost_minor','win_minor','base_cost_minor','multiplier','demo_reconnect_adjustment_minor','native_free_counter_difference_minor','native_free_counter_minor','free_micro_payout_minor','cash_packet_win_minor','bonus_packet_win_minor','decisions','win_source','prior_evaluations']if k in c}})
   done={m['mode']for m in g['modes']if m['complete']};g['complete']=bool(proof['mode_cost_factors'])and bool(proof.get('all_game_modes_complete'))and proof.get('contract_review_complete')and done==set(proof['mode_cost_factors']);g['status']='complete_declared_modes'if g['complete']else'needs_review';g['locked_options']=sorted(set(proof['mode_cost_factors'])-done);g['uncertain_play_attempts']=sum(c.get('state')=='sent_or_uncertain'for c in proof['cases']);g['historical_interrupted_demo_rounds']=len(proof.get('historical_interrupted_demo_rounds',[]))
   if proof.get('prior_run_report'):g['prior_run_report']=proof['prior_run_report']
   if proof.get('validation_exception')and proof.get('all_native_modes_attempted'):g.update(status='validation_failed',complete=False,review_complete=True,validation_exception=proof['validation_exception'])
   g['historical_failed_checks']=sum(v is False for c in proof['cases']for e in c.get('prior_evaluations',[])for v in(e.get('checks')or{}).values())
   if g['complete']or g['status']=='validation_failed':g.pop('pending_reason',None)
  games.append(g)
 modes=[m for g in games for m in g['modes']];completed=sum(g['complete']for g in games);failed=sum(g['status']=='validation_failed'for g in games);d={'provider':'playson','name':'Playson','updated_at':datetime.now(timezone.utc).isoformat(),'catalog':len(games),'catalog_scope':'100 captured slots plus canonical TEST API additions; full catalogue end not independently confirmed','completed_games':completed,'complete_modes':sum(m['complete']for m in modes),'pending':len(games)-completed-failed,'failed_games':failed,'no_demo':0,'unavailable':0,'checks_passed':sum(v is True for m in modes for v in m['checks'].values()),'checks_failed':sum(v is False for m in modes if m.get('validation_concluded')or m['complete']for v in m['checks'].values()),'historical_failed_checks':sum(g['historical_failed_checks']for g in games),'label':'Pruebas HTTP XML por el servicio público de demos','note':str(completed)+' slots completos; '+str(failed)+' con fallos; '+str(len(games)-completed-failed)+' pendientes de pruebas o resolución del identificador demo. Las 16 rondas del HAR se conservan como referencia.','coverage':'Normal mínima y cada compra declarada. Cada bonus conserva sus pasos bajo la apuesta que lo originó. Solo saldo ficticio.','har_reference':{'rounds':reference['rounds_verified'],'checks':reference['checks_passed'],'internal_steps':reference['bonus_continuation_steps']},'games':games,'excluded':[]}
 d.update(catalog_metadata(catalog,source));return d

def publish():
 common.STATES['pending_official_launch']='Pendiente de acceso a demo'
 d=build();common.publish_provider(d);folder=ROOT/'demo-dashboard/playson';ref=json.loads((OUT/'har-reference.json').read_text(encoding='utf8'));(folder/'har-reference.json').write_text(json.dumps(ref,ensure_ascii=False,indent=2),encoding='utf8');(folder/'plan-first-100.json').write_text((OUT/'plan.json').read_text(encoding='utf8'),encoding='utf8')
 catalog=json.loads((OUT/'catalog-current.json').read_text(encoding='utf8'));plan={'provider':'Playson','scope':'All currently identified public demo slots','full_catalog_total':d['full_catalog_total'],'catalog_complete':d['catalog_complete'],'fictional_demo_only':True,'games':catalog['games']};(folder/'plan-all-identified.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
 if d['catalog_complete']:
  for name in ['catalog-complete.json','catalog-coverage.json']:shutil.copyfile(OUT/name,folder/name)
  archived=OUT/catalog['snapshot_path'];target=folder/catalog['snapshot_path'];target.mkdir(parents=True,exist_ok=True)
  for name in ['manifest.json',*[p['file']for p in catalog['pages']]]:shutil.copyfile(archived/name,target/name)
 p=folder/'index.html';s=p.read_text(encoding='utf8');s=s.replace('<h1>','<p><a href="har-reference.json">Rondas originales del HAR y saldos</a> · <a href="plan-first-100.json">Primeros 100 del HAR</a> · <a href="plan-all-identified.json">Todos los slots identificados</a></p><h1>',1);p.write_text(s,encoding='utf8')
 hub=ROOT/'demo-dashboard/providers.html';text=hub.read_text(encoding='utf8');pattern=r'<section class="card"><h2>Playson</h2>.*?</section>';card=common.card(d)
 if re.search(pattern,text,re.S):text=re.sub(pattern,lambda m:card,text,flags=re.S)
 else:
  marker='</div><nav>';index=text.rfind(marker);assert index>=0,'Provider card container absent';text=text[:index]+card+text[index:]
 hub.write_text(text,encoding='utf8');return d
if __name__=='__main__':
 d=publish();print(json.dumps({k:v for k,v in d.items()if k not in ['games','excluded']},ensure_ascii=False))
