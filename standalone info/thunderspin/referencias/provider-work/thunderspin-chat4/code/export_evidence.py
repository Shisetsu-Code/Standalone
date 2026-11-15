"""Explicit allowlist export, offline replay, credential exclusion and hashes."""
import json,pathlib,hashlib,shutil,collections,re,sys
from report import build,ROOT
from native import audit_packets

def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def sanitize(x):
 if isinstance(x,dict):
  return {k:('[REDACTED]' if re.search(r'^(sid|sessionid|token|cookie|authorization|password|secret|mgckey)$',k,re.I) else sanitize(v)) for k,v in x.items() if k not in ('transport_journal','source_init_reference')}
 if isinstance(x,list):return [sanitize(v) for v in x]
 if isinstance(x,str):return x.replace(str(ROOT),'[WORKSPACE]')
 return x
def main():
 report=build()
 assert not report['audit_errors'],report['audit_errors']
 dest=ROOT/'results/evidence-final'
 if dest.exists():raise ValueError('export_exists_inspect_before_overwrite')
 dest.mkdir()
 verified=report['verified_cases'];counts=collections.Counter(c['mode'] for c in verified)
 preparations=sum(c['mode'].startswith('GAMBLE_PREP_') for c in verified)
 assert counts['NORMAL']==62 and counts['GAMBLE']==3
 report.update(status='finished_partial_unresolved_original_round',normal_games_verified=counts['NORMAL'],verified_mode_cases=len(verified)-preparations,preparation_rounds=preparations,case_mode_counts=dict(counts),captured_evidence_is_separate=True)
 write(ROOT/'results/provider-report.json',report)
 for name in ['catalogue.json','capture-sources.json','captured-round-audit.json','provider-report.json']:
  write(dest/'results'/name,sanitize(json.loads((ROOT/'results'/name).read_text(encoding='utf-8'))))
 index=[]
 for item in verified+report['pending_cases']:
  p=ROOT/item['case_file'];c=json.loads(p.read_text(encoding='utf-8'))
  init=pathlib.Path(c.get('source_init_reference') or ROOT/'private/sessions'/('own-'+c['session_fingerprint'])/'init-journal.json')
  initrel='init/'+c['session_fingerprint']+'.json';caserel='cases/'+c['game']+'/'+p.name
  clean=sanitize(c)
  if c['status']=='verified' and 'error' in clean:clean['resolved_adapter_history']=clean.pop('error')
  clean['init_reference']=initrel
  write(dest/caserel,clean);write(dest/initrel,sanitize(json.loads(init.read_text(encoding='utf-8'))))
  index.append({'case':caserel,'init':initrel,'status':c['status'],'original_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 write(dest/'case-index.json',index)
 for p in (ROOT/'private/holds').glob('*.json'):write(dest/'holds'/p.name,sanitize(json.loads(p.read_text(encoding='utf-8'))))
 for p in (ROOT/'private/plans').glob('*.json'):write(dest/'plans'/p.name,sanitize(json.loads(p.read_text(encoding='utf-8'))))
 refs=[]
 for p in (ROOT/'private/references').glob('*/client.js'):
  folder=p.parent;meta={'game_slug':folder.name,'client_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  for name in ['client-journal.json','launch-journal.json','contract.json','gamble-contract.json','wheel-contract.json','buy-feature-contract.json']:
   q=folder/name
   if q.exists():meta[name]=sanitize(json.loads(q.read_text(encoding='utf-8')))
  refs.append(meta)
 write(dest/'native-source-references.json',refs)
 for name in ['native.py','contracts.py']:
  shutil.copyfile(ROOT/'code'/name,dest/name)
 replay='''import json,pathlib\nfrom native import audit_packets\nr=pathlib.Path(__file__).resolve().parent\nn=0\nfor row in json.loads((r/'case-index.json').read_text(encoding='utf-8')):\n if row['status']!='verified':continue\n c=json.loads((r/row['case']).read_text(encoding='utf-8'));i=json.loads((r/row['init']).read_text(encoding='utf-8'));i['response']['Balance']['ScoreCents']=c['balance_before_cents']\n a=audit_packets([i]+c['journal']);assert len(a['closed_rounds'])==1 and not a['unfinished_rounds'];n+=1\nprint({'verified_closed_rounds':n,'audit_errors':0,'unresolved_cases_preserved':sum(x['status']!='verified' for x in json.loads((r/'case-index.json').read_text(encoding='utf-8')))})\n'''
 (dest/'audit.py').write_text(replay,encoding='utf-8')
 summary=f'''# ThunderSpin — verificación parcial

Catálogo oficial: 63 entradas; 62 demos públicas. Se verificaron las 62 normales al mínimo nativo, 34 compras y 3 gambles: 99 casos de modalidad. Otras 3 rondas mínimas fueron preparación explícita de gamble, sin contarlas como cobertura normal adicional. Total: 102 rondas cerradas y conciliadas; cero errores al reauditar sus journals originales. Los gambles usan una sola elección nativa; no se recorrieron todos los tamaños, líneas ni resultados aleatorios.

## Pendiente real

Zeus Riches Megaways: compra original de 700 céntimos sin liquidación probada. El adaptador envió SkipInteractive fuera de secuencia y recibió código nativo 409 (HTTP 200). El cliente exige primero Roll. Se corrigió el contrato y funcionó en Rich Leprechaun; al consultar una sola vez la sesión propia de Zeus, LastResult fue null y la ronda original no estaba disponible. Esto no demuestra crédito ni cierre ni permite atribuir la causa a expiración. No se repitieron compra ni control rechazado. El caso y sus paquetes se conservan como hold.

La entrada «Thunderspin» (ordinal 63) no publica URL demo en el catálogo oficial. No se inventó un lanzamiento. Por estos pendientes, el resultado no es cobertura completa.

## Integración y reproducción

HTTP nativo: _Initialise, _Roll, _BuyBonus, _AcceptWin y _Gamble. Nuevas sesiones anónimas con Balance.Demo=true; importes nativos en céntimos y mínimo CoinValue/BetLevel. Host, slotcode, códigos de compra, controles y continuaciones derivados de cliente oficial. Inicialización, precios, balances y secuencias completos en init/ y cases/; hashes y procedencia del cliente en native-source-references.json. user_input de Indian Call conserva el historial de celdas públicas; no usa premios ocultos. AcceptWin acredita únicamente una oferta real previa. Gamble sustituye el premio retenido, sin sumarlo dos veces.

Ejecutar offline dentro de evidence/: `python -B audit.py`. Resultado esperado: 102 rondas verificadas y un caso retenido. Verificar SHA256SUMS.json para integridad. Los hashes original_sha256 enlazan los registros privados originales con su copia saneada; no equivalen al hash de la copia.

Las 15 rondas cerradas de los HAR aportados son evidencia capturada separada y no se cuentan entre las pruebas nuevas. No se reutilizaron sus credenciales. Exportación por lista permitida: sin credentials.json, SID válidos, cookies, tokens, HAR crudos, perfiles ni HTML privado. No hay revisión automática activa.
'''
 (ROOT/'results/INFORME.md').write_text(summary,encoding='utf-8');(dest/'INFORME.md').write_text(summary,encoding='utf-8')
 # Test exact private credential values without printing them.
 secrets=[]
 def collect(x):
  if isinstance(x,dict):
   for k,v in x.items():
    if re.fullmatch('sid|sessionid|token|cookie|authorization|password|secret|mgckey',k,re.I) and isinstance(v,str) and len(v)>7:secrets.append(v)
    else:collect(v)
  elif isinstance(x,list):
   for v in x:collect(v)
 for p in (ROOT/'private/sessions').glob('*/credentials.json'):collect(json.loads(p.read_text(encoding='utf-8')))
 for p in dest.rglob('*'):
  if p.is_file():
   data=p.read_text(encoding='utf-8');assert not any(s in data for s in secrets),str(p)
 manifest={str(p.relative_to(dest)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.rglob('*')) if p.is_file()}
 write(dest/'SHA256SUMS.json',manifest)
 print({'exported_files':len(manifest),'credential_leaks':0,'verified_rounds':len(verified),'verified_modes':len(verified)-preparations,'pending_cases':len(report['pending_cases'])})
if __name__=='__main__':main()
