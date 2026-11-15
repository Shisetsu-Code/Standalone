"""3 Oaks reports, isolated provider navigation and individual bonus steps."""
import json
from html import escape as e
from provider_reports import page,publish
from threeoaks_run import ROOT,FOLDER,read,digest
from threeoaks_layout import BATCHES,batch_folder,batch_games

def current_audit(folder=None):
    folder=FOLDER if folder is None else folder
    a=read(folder/'audit.json',{})
    if not a.get('input_hashes'):return {}
    for name,sha in a['input_hashes'].items():
        p=ROOT/name
        if not p.exists() or digest(p)!=sha:return {}
    return a

def hub_card():
    normal=special=0;passed=True;links=[]
    for name in BATCHES:
        folder=batch_folder(name);a=current_audit(folder);rows=read(folder/'rounds.json',[])
        normal+=a.get('normal_cases',sum(r['status']=='completed' and r['kind']=='normal' for r in rows))
        special+=a.get('purchase_cases',sum(r['status']=='completed' and r['kind']=='buy' for r in rows))+a.get('booster_cases',sum(r['status']=='completed' and r['kind']=='booster' for r in rows))
        passed=passed and a.get('passed',False)
        links.append('<a href="threeoaks/batches/'+name+'/index.html">Lote '+name.replace('-','–')+'</a>')
    return '<section class="card"><h2>3 Oaks Gaming</h2><strong>'+str(normal)+' / 103</strong><p>Normales conciliadas · '+str(special)+' compras y activadores. '+('Auditado.' if passed else 'En proceso; consultar pendientes.')+'</p><p>103 juegos en el catálogo.</p>'+' · '.join(links)+' · <a href="threeoaks/index.html">Catálogo</a></section>'

def render():
    a=current_audit();cat=read(FOLDER/'catalog.json',[]);rows=read(FOLDER/'rounds.json',[]);inv=read(FOLDER/'inventory.json',[])
    normals=sum(r['status']=='completed' and r['kind']=='normal' for r in rows);buys=sum(r['status']=='completed' and r['kind']=='buy' for r in rows);boosts=sum(r['status']=='completed' and r['kind']=='booster' for r in rows)
    body='<nav><a href="../../../providers.html">Proveedores</a> · <a href="../../index.html">Catálogo 3 Oaks</a> · <a href="rounds.json">Resultados JSON</a> · <a href="inventory.json">Inventario completo</a> · <a href="audit.json">Auditoría</a></nav><h1>3 Oaks Gaming · Lote '+FOLDER.name.replace('-','–')+'</h1><div class="stats">'
    for count,label in [(str(normals)+' / '+str(len(batch_games())),'Normales cerradas'),(buys,'Compras cerradas'),(boosts,'Activadores cerrados')]:body+='<section class="card"><strong>'+str(count)+'</strong>'+label+'</section>'
    body+='</div><p>Solo demos oficiales con saldo ficticio FUN. Cada compra se registra como una entrada; sus tiradas gratis, respins y recogidas aparecen por separado dentro del detalle. Los premios acumulados no se suman entre pasos.</p><p class="'+('ok' if a.get('passed') else 'pending')+'">'+('Entradas, costes, cierres y saldos auditados.' if a.get('passed') else 'Auditoría parcial: '+str(a['verified_cases'])+' casos verificados; el lote sigue incompleto.' if a.get('verified_cases') is not None else 'Pruebas en proceso. Una ronda cerrada sigue pendiente de auditoría hasta verificar sus evidencias.')+'</p>'
    if a.get('unpriced_modes_not_executed'):body+='<p class="pending">Opciones sin precio o acción publicados: '+str(len(a['unpriced_modes_not_executed']))+'. No se ejecutan ni cuentan como pruebas terminadas.</p>'
    state=read(FOLDER/'run-status.json',{})
    if state.get('message'):body+='<section class="card pending"><h2>Estado de la conexión</h2><p>'+e(state['message'])+'</p></section>'
    if a.get('pending_cases'):body+='<p class="pending">Quedan '+str(len(a['pending_cases']))+' casos pendientes. Los rechazos y las solicitudes sin respuesta confirmada no cuentan como rondas cerradas.</p>'
    if a.get('partial_attempts_not_completed'):body+='<p class="pending">Hay '+str(len(a['partial_attempts_not_completed']))+' intento anterior incompleto preservado. Se muestra separado de su prueba de reemplazo.</p>'
    body+='<input placeholder="Buscar juego o modo" oninput="document.querySelectorAll(\'tr.game\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))"><table><thead><tr><th>#</th><th>Juego</th><th>Pruebas y detalle</th></tr></thead><tbody>'
    for game in cat:
        info=next((d for d in inv if d.get('game',{}).get('id')==game['id']),{});detail=''
        for mode in info.get('modes',[]):
            case=game['id']+'--'+mode['key'];r=next((r for r in rows if r['case']==case),None);label={'normal':'Normal','buy':'Compra','booster':'Activador'}.get(mode['kind'],mode['kind'])+' '+('' if mode['kind']=='normal' else str(mode.get('mode_id',mode['key'])))
            if r:
                state='Cerrada · '+('saldo auditado' if case in a.get('verified_case_ids',[]) else 'pendiente de auditoría') if r['status']=='completed' else 'Por revisar'
                detail+='<p><a href="../../round.html?case='+e(case)+'&amp;batch='+FOLDER.name+'">'+e(label)+'</a> · '+state+'</p>'
                if r.get('error'):detail+='<small>'+e(r['error'])+'</small>'
            else:detail+='<p>'+e(label)+' · '+('Pendiente' if mode.get('supported') else 'Sin precio o acción publicados; no ejecutada' if mode.get('error')=='buy_price_or_action_unpublished' else 'Formato por revisar: '+e(mode.get('error','')) )+'</p>'
        if not detail:detail=e(info.get('error','Inventario pendiente'))
        body+='<tr class="game"><td>'+str(game['ordinal'])+'</td><td>'+e(game['name'])+'</td><td>'+detail+'</td></tr>'
    publish(FOLDER/'index.html',page('3 Oaks · Pruebas',body+'</tbody></table>'))
    all_games=read(ROOT/'threeoaks/catalog.json',[]);body='<nav><a href="../providers.html">Proveedores</a> · <a href="batches/1-100/index.html">Lote 1–100</a> · <a href="batches/101-103/index.html">Lote 101–103</a></nav><h1>3 Oaks · '+str(len(all_games))+' juegos</h1><table><tr><th>#</th><th>Juego</th><th>Estado</th></tr>'
    for g in all_games:
        name='1-100' if g['ordinal']<=100 else '101-103'
        body+='<tr><td>'+str(g['ordinal'])+'</td><td>'+e(g['name'])+'</td><td><a href="batches/'+name+'/index.html">Lote '+name.replace('-','–')+'</a></td></tr>'
    publish(ROOT/'threeoaks/index.html',page('3 Oaks · Catálogo',body+'</table>'))
    viewer='''<nav><a id="back" href="batches/1-100/index.html">Volver al lote</a> · <a href="../providers.html">Proveedores</a></nav><h1 id="title">Ronda 3 Oaks</h1><div id="summary"></div><h2>Pasos de la ronda</h2><p>Los acumulados se muestran como referencia: no se suman entre pasos.</p><div id="steps"></div><script>
const add=(tag,text,parent)=>{const el=document.createElement(tag);el.textContent=text;parent.append(el);return el};
async function main(){const id=new URLSearchParams(location.search).get('case');if(!/^[a-z0-9_-]+$/.test(id||''))throw Error('Caso inválido');const batch=new URLSearchParams(location.search).get('batch')||'1-100';if(!['1-100','101-103'].includes(batch))throw Error('Lote inválido');const base='batches/'+batch+'/';document.querySelector('#back').href=base+'index.html';const link=base+'traces/'+id+'.json',r=await fetch(link,{cache:'no-store'});if(!r.ok)throw Error('Caso no encontrado');const d=await r.json(),s=d.summary,box=document.querySelector('#summary');document.querySelector('#title').textContent=s.name+' · '+s.key;add('p',s.status==='completed'?'Ronda cerrada · saldo conciliado':'Por revisar',box);if(s.error)add('p',s.error,box);if(s.scale)add('p','Saldo FUN: '+s.balance_before_native/s.scale+' → '+(s.balance_after_native==null?'pendiente':s.balance_after_native/s.scale)+' · Coste: '+s.cost_native/s.scale+' · Premio total: '+(s.win_native==null?'pendiente':s.win_native/s.scale),box);add('a','Descargar evidencia JSON',box).href=link;for(const attempt of d.previous_attempts||[]){const note=add('section','',box);add('h2','Intento anterior preservado',note);add('p',attempt.status==='rejected_before_debit'?'Solicitud rechazada sin descuento; no cuenta como ronda completada.':'Ronda original incompleta; su reemplazo es otra prueba y no completa el intento original.',note);if(/^partial-rounds\/[a-z0-9_-]+\.json$/.test(attempt.file))add('a','Ver evidencia del intento anterior',note).href=base+attempt.file;}if(d.classification_correction){const correction=d.classification_correction;add('h2','Clasificación corregida',box);add('p','El cliente numera sus opciones desde cero. Esta ronda aceptada corresponde a la compra 2; se corrigió su clasificación y coste sin repetirla ni modificar las solicitudes o respuestas.',box);if(/^classification-corrections\/[a-z0-9_-]+\.json$/.test(correction.file))add('a','Ver registro original preservado',box).href=base+correction.file;}const out=document.querySelector('#steps'),table=add('table','',out),head=add('tr','',table);for(const t of ['Paso','Acción','Fase','Restantes','Acumulado · no sumar','Saldo FUN'])add('th',t,head);for(const [i,step] of d.trace.entries()){const c=step.response?.context,u=step.response?.user;if(step.request.command!=='play')continue;const row=add('tr','',table),part=c?.[c.current]||{};for(const v of [i+1,step.request.action.name,c?.current||'sin respuesta',part.rounds_left??'—',part.total_win==null?'—':part.total_win/s.scale,u?.balance==null?'—':u.balance/s.scale])add('td',String(v),row);}for(const [i,step] of d.trace.entries()){const x=add('details','',out);add('summary','Paso '+(i+1)+' · '+(step.request.action?.name||step.request.command)+' · '+step.status,x);add('pre',JSON.stringify(step,null,2),x);}}
main().catch(e=>document.querySelector('#summary').textContent=e.message);
</script>'''
    publish(ROOT/'threeoaks/round.html',page('3 Oaks · Ronda',viewer))
    from provider_reports import render_hub
    render_hub()
if __name__=='__main__':render()
