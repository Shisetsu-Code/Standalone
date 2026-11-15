"""Publish reviewed Chat4 metadata only; retain originals in the isolated workspace."""
from pathlib import Path
import collections,hashlib,html,json,re,sys,time
R=Path(__file__).resolve().parents[3];B=R/'provider-work/peterandsons-chat4';D=R/'demo-dashboard'
sys.path.insert(0,str(R/'parallel_tools'))
from contracts import _mode,_text
from workspaces import exclusive,atomic,atomic_text
read=lambda p:json.loads(p.read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ref=lambda p:{'path':p.relative_to(R).as_posix(),'sha256':sha(p)}
reviewpath=Path(__file__).with_name('peterandsons-chat4-delivery-root-review.json');review=read(reviewpath)
source=B/'results/provider-report.json';assert sha(source)==review['source_report']['sha256']
report=read(source);seq=read(B/'results/inks-pints-replication.json')
assert review['verified_modes']==239 and review['catalogue_games']==75 and seq['status']=='verified'and seq['verified_rounds']==7
games=[]
for game in report['games']:
 g={k:_text(game[k],identifier=k=='id')for k in ['id','title','classification','status']}
 g['modes']=[_mode({k:v for k,v in mode.items()if k in ['id','kind','status','cost','payout','checks','evidence']},B.resolve())for mode in game['modes']]
 games.append(g)
summary={'catalogue_games':75,'normal_modes_verified':75,'identified_minimum_modes_verified':239,'normal':75,'special':52,'purchase_including_conditional':112,'conditional_purchases':2,'internal_steps':1870,'games_complete_at_identified_minimum':70,'historical_settlement_holds':5,'unstarted_purchases':3,'all_modes_complete':False,'scope':'Modos identificados al mínimo nativo; otras apuestas y selecciones de líneas no recorridas por completo.'}
replication={'game':'inks-pints','status':'verified','rounds':[{'index':x['index'],'action':_text(x['action'],identifier=True),'bet':x['bet'],'payout':x['audit']['payout'],'balance_after':x['audit']['balance_after'],'status':'verified'}for x in seq['rounds']],'balance_before':10000,'balance_after':9969,'cost':312,'payout':281,'previous_hold_separate':True,'counts_as_additional_catalogue_modes':False}
safe={'schema_version':1,'provider':'peterandsons','provider_name':'Peter & Sons','summary':summary,'games':games,'additional_verified_sequence':replication,'historical_incidents':[{'game':v['game'],'mode':v['mode'],'error':v['error'],'status':'historical_unreconciled'}for v in review['held_original_settlements']],'pending_purchases':review['pending_not_started'],'evidence_review_sha256':sha(reviewpath)}
esc=lambda x:html.escape(str(x),quote=True)
labels={'normal':'Normal','special':'Especial / activador','purchase':'Compra','antebet':'Antebet','verified_remote':'Verificado en demo','needs_review':'Cobro anterior sin conciliar','pending':'Sin iniciar','complete':'Plan al mínimo completo'}
rows=[]
for g in games:
 modes=''.join('<tr><td>'+esc(m['id'])+'</td><td>'+esc(labels.get(m['kind'],m['kind']))+'</td><td>'+esc(m.get('cost','—'))+'</td><td>'+esc(m.get('payout','—'))+'</td><td>'+esc(labels.get(m['status'],m['status']))+'</td></tr>'for m in g['modes'])
 note=' · <a href="#inks-pints">7 operaciones posteriores completadas</a>'if g['id']=='inks-pints'else ''
 rows.append('<details><summary>'+esc(g['title'])+' · '+str(sum(m['status']=='verified_remote'for m in g['modes']))+'/'+str(len(g['modes']))+' modos al mínimo'+note+'</summary><table><tr><th>Acción</th><th>Tipo</th><th>Coste</th><th>Premio</th><th>Estado</th></tr>'+modes+'</table></details>')
sequence=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>'for v in [x['index'],x['action'],x['bet'],x['payout'],x['balance_after'],'Completada'])+'</tr>'for x in replication['rounds'])
incidents=''.join('<tr><td>'+esc(next(g['title']for g in games if g['id']==x['game']))+'</td><td>'+esc(x['mode'])+'</td><td>Rechazo de cobro en una sesión anterior; conservado sin reintentos</td></tr>'for x in safe['historical_incidents'])
pending=''.join('<li>'+esc(x['game'])+' · '+esc(x['mode'])+'</li>'for x in safe['pending_purchases'])
page='''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Peter &amp; Sons · Resultados</title><style>body{font:16px system-ui;background:#101827;color:#e2e8f0;max-width:1150px;margin:32px auto;padding:0 24px}a{color:#7dd3fc}.stats{display:flex;gap:16px;flex-wrap:wrap}.card,details{background:#1e293b;padding:18px;border-radius:10px;margin:14px 0}.card{flex:1}strong{font-size:28px;color:#6ee7b7}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #475569}summary{cursor:pointer}input{padding:12px;width:95%;background:#1e293b;color:white;border:1px solid #475569;border-radius:8px}.ok{color:#6ee7b7}</style><body><a href="../providers.html">Todos los proveedores</a><h1>Peter &amp; Sons</h1><div class="stats"><section class="card"><strong>75 / 75</strong><p>Slots con tirada normal verificada</p></section><section class="card"><strong>239 modos</strong><p>75 normales · 52 especiales · 112 compras, incluidos 2 extras condicionales</p></section><section class="card"><strong>70 planes</strong><p>Completos para los modos identificados al mínimo nativo</p></section></div><p>1.870 pasos internos conservados. Las pruebas de otras cantidades, las capturas HAR y las rondas preparatorias se registran por separado.</p><p><a href="report.json">Resultados por juego y modo</a> · <a href="verification-summary.json">Resumen de comprobaciones</a></p><section class="card" id="inks-pints"><h2>Inks &amp; Pints · prueba posterior completada</h2><p class="ok">Las 7 operaciones de la secuencia posterior fueron cobradas y sus saldos conciliados.</p><p>Saldo demo: 10.000 → 9.969 · Coste: 312 · Premios: 281. Compra de bonus: 150 → 149. Jackpot: 150 → 132.</p><p>La sesión manual aportada en el HAR también confirma un Jackpot cobrado. El rechazo de otra ronda anterior del chat queda en el historial y no indica que tengas una operación manual pendiente. Esta secuencia usa importes distintos del mínimo y no se suma otra vez a los modos del catálogo.</p><table><tr><th>Orden</th><th>Acción</th><th>Apuesta</th><th>Premio</th><th>Saldo</th><th>Estado</th></tr>'''+sequence+'''</table></section><h2>Catálogo y modos</h2><label>Buscar juego <input id="search" placeholder="Nombre del juego" oninput="document.querySelectorAll('#games>details').forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(this.value.toLowerCase()))"></label><div id="games">'''+''.join(rows)+'''</div><h2>Compras sin iniciar</h2><ul>'''+pending+'''</ul><details><summary>Historial de cinco rechazos de cobro en sesiones anteriores</summary><p>Las rondas originales se conservan sin dar por conciliado un saldo que no fue confirmado. Las pruebas posteriores correctas se muestran aparte.</p><table><tr><th>Juego</th><th>Acción</th><th>Incidencia histórica</th></tr>'''+incidents+'''</table></details></body></html>'''
card='<section class="card"><h2>Peter &amp; Sons</h2><strong>75 / 75 slots</strong><p>239 modos verificados al mínimo: 75 normales, 52 especiales y 112 compras.</p><p>70 planes completos al mínimo. Inks &amp; Pints: 7 operaciones posteriores completadas y conciliadas; incidencias anteriores separadas.</p><p><a href="peterandsons/index.html">Catálogo, modos e historial</a> · <a href="peterandsons/index.html#inks-pints">Resultados de Inks &amp; Pints</a></p></section>'
# Only allowlisted metadata reaches public files. Never copy private journals or sessions.
publicbytes=json.dumps(safe,ensure_ascii=False).encode()+page.encode()
for cred in (B/'private/sessions').glob('*/credentials.json'):
 for k,v in read(cred).items():
  if k in ['key','token']and v:assert str(v).encode()not in publicbytes
with exclusive(R/'provider-work/coordination/publication.lock'):
 hub=D/'providers.html';before=hub.read_text(encoding='utf8');oldcards=re.findall(r'<section class="card">.*?</section>',before,re.S);oldothers=[v for v in oldcards if '<h2>Peter &amp; Sons</h2>'not in v and '<h2>Peter & Sons</h2>'not in v]
 pattern=r'<section class="card"><h2>Peter (?:&amp;|&) Sons</h2>.*?</section>'
 if re.search(pattern,before,re.S):after=re.sub(pattern,lambda _:card,before,flags=re.S)
 else:assert before.count('</div><nav>')==1;after=before.replace('</div><nav>',card+'</div><nav>')
 newcards=re.findall(r'<section class="card">.*?</section>',after,re.S);assert len(newcards)==14 and [v for v in newcards if '<h2>Peter &amp; Sons</h2>'not in v]==oldothers
 target=D/'peterandsons';target.mkdir(exist_ok=True)
 atomic(target/'report.json',safe);atomic(target/'verification-summary.json',{'summary':summary,'additional_verified_sequence':replication,'review_sha256':sha(reviewpath),'private_credentials_published':False});atomic_text(target/'index.html',page)
 archive=R/'provider-work/coordination/history'/('providers-before-peterandsons-'+sha(hub)+'.html');archive.parent.mkdir(exist_ok=True)
 if not archive.exists():archive.write_bytes(hub.read_bytes())
 atomic_text(hub,after)
 atomic(R/'provider-work/coordination/imports/peterandsons-dashboard.json',{'status':'published_reviewed_partial','provider':'peterandsons','source_report':ref(source),'root_review':ref(reviewpath),'additional_sequence':ref(B/'results/inks-pints-replication.json'),'public_report':ref(target/'report.json'),'public_page':ref(target/'index.html'),'other_provider_cards_unchanged':len(oldothers),'updated_at':time.time()})
print(json.dumps({'provider':'peterandsons','games':len(games),'verified_modes':239,'additional_verified_rounds':7,'cards':len(newcards),'other_cards_unchanged':len(oldothers)}))
