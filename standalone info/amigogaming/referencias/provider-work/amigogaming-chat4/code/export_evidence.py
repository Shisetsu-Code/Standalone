"""Allowlist-only standalone sanitized audit bundle, no credentials or raw HAR."""
import pathlib,json,re,hashlib,shutil,zipfile,datetime
from discover import ROOT,save
from report import build
def sanitize(x):
 if isinstance(x,dict):return {k:('[REDACTED]' if re.fullmatch('session|sid|sign|token|cookie|authorization|password|secret|mgckey|traceId',k,re.I) else sanitize(v)) for k,v in x.items()}
 if isinstance(x,list):return [sanitize(v) for v in x]
 if isinstance(x,str):
  x=x.replace(str(ROOT),'[WORKSPACE]');return re.sub(r'([?&](?:session|sid|sign|token|mgckey)=)[^&#\s]+',r'\1[REDACTED]',x,flags=re.I)
 return x
def main():
 report=build();assert not report['audit_errors'];assert not report['unvisited'] or (ROOT/'private/remote-block.json').exists(),'campaign_not_exhausted'
 tag=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');dest=ROOT/'export'/('amigogaming-evidence-'+tag);dest.mkdir(parents=True,exist_ok=False);save(dest/'provider-report.json',sanitize(report));save(dest/'catalogue.json',json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf-8')));save(dest/'capture-sources.json',json.loads((ROOT/'results/capture-sources.json').read_text(encoding='utf-8')));index=[];refs=[]
 for p in sorted((ROOT/'private/rounds').glob('*/*.json')):
  c=json.loads(p.read_text(encoding='utf-8'));case_rel='cases/'+str(c['game_id'])+'/'+p.name;init_rel='init/'+hashlib.sha256(c['init_reference'].encode()).hexdigest()[:16]+'.json';save(dest/init_rel,sanitize(json.loads((ROOT/c['init_reference']).read_text(encoding='utf-8'))));entry={'case':case_rel,'init':init_rel,'status':c['status'],'original_sha256':hashlib.sha256(p.read_bytes()).hexdigest()};index.append(entry)
  for packet in c['journal']:
   if packet.get('recovery_reference'):
    q=ROOT/packet['recovery_reference'];ref='recovery/'+str(c['game_id'])+'/'+q.name;save(dest/ref,sanitize(json.loads(q.read_text(encoding='utf-8'))));packet['recovery_export_reference']=ref
  save(dest/case_rel,sanitize(c))
  cp=ROOT/c['source_client_reference'];source_hash=hashlib.sha256(cp.read_bytes()).hexdigest();refs.append({'game_id':c['game_id'],'source_reference':c['source_client_reference'],'sha256':source_hash})
 save(dest/'case-index.json',index);save(dest/'client-references.json',refs)
 for p in (ROOT/'private/plans').glob('*.json'):
  plan=json.loads(p.read_text(encoding='utf-8'));save(dest/'plans'/p.name,sanitize(plan))
  if plan.get('excluded_non_slot'):save(dest/'excluded-init'/p.name,sanitize(json.loads((ROOT/plan['init_reference']).read_text(encoding='utf-8'))))
 for p in (ROOT/'private/sessions').glob('*/client-fetch.json'):save(dest/'public-source-fetches'/p.parent.name/'client-fetch.json',sanitize(json.loads(p.read_text(encoding='utf-8'))))
 for p in (ROOT/'private/discovery').glob('catalogue-*.json'):save(dest/'catalogue-provenance'/p.name,sanitize(json.loads(p.read_text(encoding='utf-8'))))
 first_client=ROOT/'private/discovery/diamond-client.json'
 if first_client.exists():save(dest/'public-source-fetches/diamond-probe/client-fetch.json',sanitize(json.loads(first_client.read_text(encoding='utf-8'))))
 save(dest/'native-api-contract.json',{'provider':'Amigo Gaming','public_catalogue':'https://amigogaming.com/fetchGames?offsetPage=<native_page>&locale=es','public_launch':{'method':'POST','url':'https://amigogaming.com/es/generateDemoGameLink','form_fields':['id','sessionType'],'csrf':'new own public portal session only'},'native_launch':'URL from the new official redirect launch parameter; new session/sign only','websocket':'endpoint and session/sign from the new official native launch; observed sdemo.amigogaming.cloud/organic2/websocket/endpoint/2','requests':{'init':'requests.InitRequest','action':'requests.ActionRequest','normal':'features.slot.action.SpinAction + native BetParams','purchase':'same native SpinAction + exact buyIns.id in buyInId','match3_and_pickme':'features.pickme.action.PickMeAction + visible unselected choice index, without betParams'},'units':{'balance.amount':'native decimal money, currency from response','win':'native credits; multiply once by native denomination','normal_cost':'bet * multiplier * denomination','purchase_cost':'normal_cost * native buyIns.price'},'closure':'native resolved state returns to finished SLOT with no initialized feature pending; one round binding throughout','ledger':'after = before - one entry cost + final cumulative win*denomination','scope':'one native minimum normal and each available native buy option; observed continuations, not all random branches','credentials':'private and excluded; never replay HAR identities'})
 if (ROOT/'private/remote-block.json').exists():save(dest/'remote-block.json',json.loads((ROOT/'private/remote-block.json').read_text(encoding='utf-8')))
 for name in ['403-before-user-requested-fresh-session.json','fresh-session-check.json','fresh-session-portal.json']:
  q=ROOT/'private/recovery'/name
  if q.exists():save(dest/'recovery-history'/name,sanitize(json.loads(q.read_text(encoding='utf-8'))))
 for p in (ROOT/'private/sessions').glob('*/init.json'):
  if p.parent.name=='game-107-1':
   save(dest/'preflight-only/107-init.json',sanitize(json.loads(p.read_text(encoding='utf-8'))));save(dest/'preflight-only/107-client.json',{'sha256':hashlib.sha256((p.parent/'client.js').read_bytes()).hexdigest(),'no_financial_action_sent':True,'stopped_on_reconnect_http':403})
 shutil.copyfile(ROOT/'code/native.py',dest/'native.py')
 script="import pathlib,json,hashlib\nfrom native import audit,minimum_bet,D\nr=pathlib.Path(__file__).resolve().parent\nfor name,sha in json.loads((r/'SHA256SUMS.json').read_text(encoding='utf-8')).items():assert hashlib.sha256((r/name).read_bytes()).hexdigest()==sha\nn=0;witnesses=0\nfor row in json.loads((r/'case-index.json').read_text(encoding='utf-8')):\n if row['status']!='verified':continue\n c=json.loads((r/row['case']).read_text(encoding='utf-8'));i=json.loads((r/row['init']).read_text(encoding='utf-8'))['response'];i['balance']['amount']=c['balance_before'];request=c['journal'][0]['request']['action']\n assert request['betParams']==minimum_bet(i)\n if c['mode']=='NORMAL':assert 'buyInId' not in request and D(c['price_multiplier'])==1\n else:\n  quote=next(b for b in i['buyIns'] if b['id']==c['mode'].removeprefix('BUY_'));assert request['buyInId']==quote['id'] and D(str(quote['price']))==D(c['price_multiplier'])\n for packet in c['journal']:\n  if packet.get('recovery_snapshot'):\n   proof=json.loads((r/packet['recovery_export_reference']).read_text(encoding='utf-8'));assert proof['response']==packet['recovery_snapshot'];witnesses+=1\n audit(i,c['journal'],c['price_multiplier']);n+=1\nprint({'verified_closed_cases':n,'hash_and_ledger_errors':0,'native_quotes_and_minima_verified':True,'recovery_witnesses_verified':witnesses})\n"
 (dest/'audit.py').write_text(script,encoding='utf-8')
 if report.get('remote_block'):
  campaign_status=f"Entrega parcial: quedan {len(report['unvisited'])} slots sin verificar. Se detuvieron nuevas entradas por una respuesta HTTP403. No se afirma su causa ni un bloqueo general del proveedor. Los casos terminados están cerrados y conciliados; los pendientes figuran en provider-report.json."
 elif report['coverage_complete']:
  campaign_status="Recorrido completo del alcance: todas las normales mínimas y compras nativas identificadas de los slots elegibles están verificadas, con sus continuaciones activadas, cierre y saldo. No quedan casos ni juegos pendientes."
 else:campaign_status=f"Recorrido todavía parcial: quedan {len(report['unvisited'])} slots sin verificar y {len(report['pending'])} casos pendientes."
 if report.get('historical_403_recovery',{}).get('status')=='fresh_public_session_initialized_successfully':campaign_status+=" Hubo un403 al reconectar una sesión antigua de Galaxy Chase. Tras petición expresa del usuario, un lanzamiento público normal NUEVO devolvió HTTP200, WS101 e inicialización con saldo; no se reutilizaron la firma anterior ni credenciales HAR, no se modificó TLS/cookies ni se saltaron retos. Ese resultado no prueba la causa exacta del fallo antiguo. La campaña continuó con demos nuevas; la evidencia anterior se conserva en recovery-history/."
 summary=f'''# Amigo Gaming — QA de demos públicas

Catálogo oficial congelado: {report['catalogue_entries']} entradas, {len(report['coming_soon'])} próxima publicación, {len(report['excluded_non_slots'])} no-slots excluidos por género nativo y {report['eligible_games']} slots elegibles. Normal mínima verificada en {report['verified_normals']} juegos; {report['verified_buys']} compras identificadas por buyIns.id/price verificadas. {len(report['pending'])} casos pendientes; {len(report['audit_errors'])} errores de auditoría. Cobertura completa del alcance: {report['coverage_complete']}.

## Estado de la campaña

{campaign_status}

3 Pharaohs: la primera demo devolvió saldo cero y rechazó la solicitud con ErrorResponse402, fondos insuficientes. Se conserva el rechazo original, separado de rondas ejecutadas. Otra demo pública nueva confirmó saldo1000 y ronda0 antes de enviar una única normal mínima, que terminó conciliada. No se alteró ningún wallet ni se reutilizaron credenciales HAR.

Alcance: una normal al mínimo nativo y cada opción buyIns que ofrece la configuración actual de cada demo, incluyendo todas las continuaciones activadas y saldo exacto. No todas las líneas, importes ni ramas aleatorias. Las definiciones de features no equivalen por sí solas a una compra disponible. Una entrada coming_soon se excluye explícitamente.

Protocolo propio: lanzamiento público nuevo por juego, HTTP y WebSocket nativo. requests.InitRequest y requests.ActionRequest; SpinAction con BetParams nativos. Compras añaden buyInId y precio como multiplicador de la apuesta base. Match3 usa PickMeAction según el cliente real; sólo elecciones aún ocultas (-1), sin usar field ni premios ocultos. Payout win se expresa en créditos y se multiplica por denomination; balance.amount es dinero decimal nativo. Cada ronda conserva el mismo round y termina únicamente cuando la cadena de estados vuelve al slot terminado, sin feature INIT pendiente. Saldo final = saldo inicial - coste + premio.

Spooky Sweets: durante dos pausas hubo una elección enviada sin respuesta consumida. Se conservaron los paquetes originales como sending y lecturas Init independientes probaron misma ronda y elección antes oculta ahora registrada. Se continuó por la siguiente opción sin reenviar elección ni apuesta. El auditor usa recovery_snapshot como testigo explícito; no fabrica respuestas ActionResponse.

Los HAR aportados no incluyen mensajes WebSocket: se usan como referencias de lanzamiento/cliente, no cuentan como rondas nuevas verificadas y sus sesiones nunca se reutilizaron. Evidencia saneada por lista permitida, sin credentials.json, cookies, firmas, SID válidos, HAR crudos, perfiles ni HTML privado. Los hashes original_sha256 corresponden a fuentes privadas originales; SHA256SUMS.json corresponde a los archivos exportados.

Reproducción offline: `python -B audit.py`. No accede a red. provider-report.json y plans/ detallan modalidades y pendientes; client-references.json y public-source-fetches/ enlazan fuentes oficiales y hashes. No se consolidó con otros proveedores ni se crearon automatizaciones.
'''
 (ROOT/'results/INFORME.md').write_text(summary,encoding='utf-8');(dest/'INFORME.md').write_text(summary,encoding='utf-8')
 secrets=[]
 def collect(x):
  if isinstance(x,dict):
   for k,v in x.items():
    if re.fullmatch('session|sid|sign|token|cookie|authorization|password|secret|mgckey',k,re.I) and isinstance(v,str) and len(v)>7:secrets.append(v)
    else:collect(v)
  elif isinstance(x,list):
   for v in x:collect(v)
 for p in (ROOT/'private/sessions').glob('*/credentials.json'):collect(json.loads(p.read_text(encoding='utf-8')))
 for p in (ROOT/'private/sessions').glob('*/launch.private.json'):collect(json.loads(p.read_text(encoding='utf-8')))
 for p in dest.rglob('*'):
  if p.is_file():
   text=p.read_text(encoding='utf-8');assert not any(s in text for s in secrets),'credential_leak'
 save(dest/'SHA256SUMS.json',{str(p.relative_to(dest)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.rglob('*')) if p.is_file()})
 archive=dest.with_suffix('.zip')
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(dest.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(dest))
 archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
 save(ROOT/'results/export-location.json',{'folder':str(dest),'zip':str(archive),'credential_leaks':0});print({'folder':str(dest),'zip':str(archive),'credential_leaks':0})
if __name__=='__main__':main()
