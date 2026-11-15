"""Play'n GO remains isolated from the five existing providers."""
from html import escape as e
from provider_reports import page,publish
from playngo_run import ROOT,FOLDER,read,digest
from playngo_paths import BATCHES,batch_path,catalog_slice

def current_audit(folder=None):
    audit=read((folder or FOLDER)/'audit.json',{})
    if not audit.get('input_hashes'):return {}
    for name,value in audit['input_hashes'].items():
        path=ROOT/name
        if not path.is_file() or digest(path)!=value:return {}
    return audit

def hub_card():
    batches=[b for b in BATCHES if (batch_path(b)/'catalog.json').exists()]
    audits=[current_audit(batch_path(b)) for b in batches]
    normal=sum(a.get('normal_cases',0) for a in audits);total=sum(len(read(batch_path(b)/'catalog.json',[])) for b in batches)
    links=' · '.join('<a href="playngo/batches/'+b+'/index.html">Lote '+b.replace('-','–')+'</a>' for b in batches)
    unavailable=sum(len(a.get('unavailable_games',[])) for a in audits)
    return '<section class="card"><h2>Play’n GO</h2><strong>'+str(normal)+' / '+str(total)+'</strong><p>Normales conciliadas · '+str(sum(a.get('go_ultra_cases',0) for a in audits))+' GoUltra · '+str(unavailable)+' demo no habilitada</p><p>477 juegos en el catálogo. '+('Lotes auditados.' if audits and all(a.get('passed') for a in audits) else 'Ver cobertura y pendientes.')+'</p>'+links+' · <a href="playngo/index.html">Catálogo</a></section>'

def render():
    batch=FOLDER.name;label=batch.replace('-','–')
    rows=read(FOLDER/'rounds.json',[]);audit=current_audit()
    cat=read(ROOT/'playngo/catalog.json',[]);scope=read(FOLDER/'catalog.json',catalog_slice(batch))
    body='<nav><a href="../../../providers.html">Proveedores</a> · <a href="../../index.html">Catálogo Play’n GO</a> · <a href="rounds.json">Resultados JSON</a> · <a href="inventory.json">Modos identificados</a> · <a href="audit.json">Auditoría</a></nav><h1>Play’n GO · Lote '+label+'</h1>'
    body+='<div class="stats"><section class="card"><strong>'+str(audit.get('normal_cases',0))+' / '+str(len(scope))+'</strong>Normales conciliadas</section><section class="card"><strong>'+str(audit.get('go_ultra_cases',0))+'</strong>Entradas GoUltra conciliadas</section><section class="card"><strong>'+str(len(audit.get('pending_cases',[])))+'</strong>Casos por revisar</section></div>'
    if audit.get('unavailable_games'):
        body+='<p class="pending">'+str(len(audit['unavailable_games']))+' demo no habilitada por el proveedor: '+e(', '.join(g['name'] for g in audit['unavailable_games']))+'. Se conserva la respuesta oficial; no se cuenta como tirada completada.</p>'
    if any(r.get('game_type')=='roulette' for r in rows):body+='<p>Ruleta: una apuesta mínima al cero. No se recorren todas las posiciones de la mesa.</p>'
    if any(r.get('game_type')=='holdem' for r in rows):body+='<p>Hold’em: una posición, ante mínimo, sin AA y Fold. Call y los premios al showdown no cuentan como probados.</p>'
    if any(r.get('game_type') in ('legacy_table','draw_game') for r in rows):body+='<p>Mesa y juegos especiales: blackjack con una posición y Stand, sin seguro; Hold’em con ante mínimo y Fold, sin AA; baccarat al jugador; ruedas en una posición; póker con una mano y reemplazo de las cinco cartas; keno con los números 1 y 2. No se prueban todas las apuestas ni decisiones posibles.</p>'
    if audit.get('partial_deals_not_completed'):body+='<p class="pending">Se conservan '+str(len(audit['partial_deals_not_completed']))+' repartos de póker parciales de diagnóstico. Sus sesiones se cerraron antes de completar la mano; no cuentan como manos terminadas. Las pruebas completas posteriores usan sesiones demo nuevas.</p>'
    body+='<p>Sesiones nuevas de las demos oficiales con moneda ficticia DEMO. Cada entrada conserva su solicitud y todas las respuestas nativas, incluidas las tiradas gratis y recogidas del premio. No se reutilizan las sesiones de los HAR.</p><p>Alcance: una entrada normal por juego y cada GoUltra identificado y habilitado. GO CRAPS se prueba con Pass Line; otras apuestas de mesa y todos los desenlaces naturales posibles quedan fuera de esta muestra.</p><p class="'+('ok' if audit.get('passed') else 'pending')+'">'+('Lote auditado: entradas, cierres y saldos verificados.' if audit.get('passed') else 'Auditoría en proceso; consultar pendientes.')+'</p><input placeholder="Buscar juego o modo…" oninput="document.querySelectorAll(\'tr.game\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))"><table><thead><tr><th>#</th><th>Juego</th><th>Pruebas y detalle</th></tr></thead><tbody>'
    for game in scope:
        cases=[r for r in rows if r['id']==game['id']]
        detail=''
        for row in cases:
            label={'craps':'Pass Line · normal','roulette':'Cero · ruleta','holdem':'Ante + Fold · Hold’em'}.get(row.get('game_type'),'Normal' if row['kind']=='normal' else 'GoUltra')
            if row.get('game_type') in ('legacy_table','draw_game'):
                native=read(FOLDER/'traces'/(row['case']+'.json'),{}).get('profile',{}).get('type')
                label={'blackjack':'Una mano · Stand','casinoholdem':'Ante + Fold','baccarat':'Baccarat · Jugador','poker':'Póker · Una mano','wheel':'Rueda · Una posición','keno':'Keno · 1 y 2','simple_slot':'Slot clásico'}.get(native,'Normal')
            state='Cerrada · saldo conciliado' if row['status']=='completed' and row['case'] in audit.get('verified_case_ids',[]) else 'Demo no habilitada' if row['status']=='unavailable' else 'Preparada' if row['status']=='ready' else 'Auditoría pendiente' if row['status']=='completed' else 'Por revisar'
            detail+='<p><a href="../../round.html?batch='+batch+'&amp;case='+e(row['case'])+'">'+label+'</a> · '+state+'</p>'
            if row.get('error'):detail+='<small>'+e(row['error'])+'</small>'
            if row.get('unavailable_reason'):detail+='<p>'+e(row['unavailable_reason'])+'</p>'
        body+='<tr class="game"><td>'+str(game['ordinal'])+'</td><td>'+e(game['name'])+'</td><td>'+(detail or 'Pendiente')+'</td></tr>'
    if audit and audit.get('free_spin_requests_observed')==0:
        body=body.replace('<input placeholder="Buscar juego o modo…"','<p>No se activaron tiradas gratis naturales en esta muestra; su cierre no cuenta como probado en vivo.</p><input placeholder="Buscar juego o modo…"')
    if not any(r.get('game_type')=='craps' for r in rows):
        body=body.replace('GO CRAPS se prueba con Pass Line; otras apuestas de mesa y todos los desenlaces naturales posibles quedan fuera de esta muestra.','Todos los desenlaces naturales posibles quedan fuera de esta muestra.')
    publish(FOLDER/'index.html',page('Play’n GO · Pruebas',body+'</tbody></table>'))
    batches=[b for b in BATCHES if (batch_path(b)/'catalog.json').exists()]
    membership={g['id']:b for b in batches for g in read(batch_path(b)/'catalog.json',[])}
    links=' · '.join('<a href="batches/'+b+'/index.html">Lote '+b.replace('-','–')+'</a>' for b in batches)
    body='<nav><a href="../providers.html">Proveedores</a> · '+links+'</nav><h1>Play’n GO · '+str(len(cat))+' juegos</h1><table><tr><th>#</th><th>Juego</th><th>Estado</th><th>Fuente</th></tr>'
    for game in cat:
        b=membership.get(game['id'])
        body+='<tr><td>'+str(game['ordinal'])+'</td><td>'+e(game['name'])+'</td><td>'+('<a href="batches/'+b+'/index.html">Lote '+b.replace('-','–')+'</a>' if b else 'Pendiente')+'</td><td><a href="'+e(game['details_url'])+'">Ficha oficial</a></td></tr>'
    publish(ROOT/'playngo/index.html',page('Play’n GO · Catálogo',body+'</table>'))
    viewer='''<nav><a href="batches/1-100/index.html">Volver al lote</a> · <a href="../providers.html">Proveedores</a></nav><h1 id="title">Ronda Play’n GO</h1><div id="summary"></div><h2>Pasos nativos de la ronda</h2><p>Cada resultado se muestra por separado. Los paquetes nativos conservan los datos completos y el indicador de cierre del saldo. Los acumulados no se suman entre pasos.</p><div id="steps"></div><script>
const add=(tag,text,parent)=>{const n=document.createElement(tag);n.textContent=text;parent.append(n);return n};
async function main(){
const query=new URLSearchParams(location.search),id=query.get('case'),batch=query.get('batch')||'1-100';if(!['1-100','101-200','201-300','301-400','401-477'].includes(batch)||!/^[a-z0-9_-]+$/.test(id||''))throw Error('Caso o lote inválido');document.querySelector('nav a').href='batches/'+batch+'/index.html';
const link='batches/'+batch+'/traces/'+encodeURIComponent(id)+'.json',response=await fetch(link,{cache:'no-store'});if(!response.ok)throw Error('Caso no encontrado');
const d=await response.json(),r=d.summary,s=document.querySelector('#summary'),steps=document.querySelector('#steps');document.querySelector('#title').textContent=r.name+' · '+({craps:'Pass Line',roulette:'Cero',holdem:'Ante + Fold'}[r.game_type]||(r.kind==='normal'?'Normal':'GoUltra'));
if(r.game_type==='legacy_table'||r.game_type==='draw_game')add('p','Variante probada: '+r.variant,s);
add('p',r.status==='completed'?'Cerrada · saldo conciliado':'Pendiente de revisión',s);if(r.error)add('p',r.error,s);if(r.scale)add('p','Saldo DEMO: '+r.balance_before_native/r.scale+' → '+r.balance_after_native/r.scale+' · Entrada: '+r.cost_native/r.scale+' · Premio: '+r.win_native/r.scale,s);add('a','Descargar evidencia JSON',s).href=link;
if(r.game_type==='holdem')add('p','Una posición, ante mínimo, sin AA y Fold. Call y showdown no probados.',s);
const table=add('table','',steps),head=add('tr','',table);for(const label of ['Paso','Fase','Gratis restantes','Premio reportado · no sumar acumulados'])add('th',label,head);
if(['legacy_table','draw_game'].includes(r.game_type)){let started=false;for(const [index,step] of d.trace.entries()){if(step.commands.some(c=>c.code===1))started=true;if(!started)continue;const tr=add('tr','',table);add('td',String(index+1),tr);add('td',step.commands.map(c=>({1:'Entrada / reparto',2:d.profile.type==='blackjack'?'Decisión de mano':'Resolución / cambio de cartas',3:'Cierre / recogida',4:'Recogida',52:'Confirmar saldo'}[c.code]||'Continuación')).join(', '),tr);add('td','—',tr);add('td',step.responses?.some(c=>c.code===52&&c.args[1]==='0')?String(r.win_native/r.scale)+' DEMO':'—',tr);}}else{
for(const [index,step] of d.trace.entries()){
const codes=step.commands.map(c=>c.code),phase=r.game_type==='craps'?'Dados':codes.includes(7)?'Tirada gratis':codes.includes(4)?'Cobro':codes.includes(2)?'Resolución interna':'Entrada';
for(const reply of step.responses||[]){const tableGame=['craps','roulette','holdem'].includes(r.game_type);if(reply.code!==(r.game_type==='roulette'?1:3))continue;const tr=add('tr','',table);add('td',String(index+1),tr);add('td',r.game_type==='roulette'?'Ruleta · número '+reply.args[0]:r.game_type==='holdem'?'Fold · resultado':phase,tr);add('td',tableGame?'—':reply.args[3]||'0',tr);const nativeWin=r.game_type==='holdem'?r.win_native:reply.args[r.game_type==='craps'?1:2];add('td',String(Number(nativeWin)/r.scale)+' DEMO',tr);}
}
}
for(const [index,step] of d.trace.entries()){const section=add('details','',steps);add('summary','Paso '+(index+1)+' · '+step.transport+' · '+step.status,section);add('pre',JSON.stringify({envío:step.commands,respuesta:step.responses},null,2),section);}
if(d.previous_attempts?.length){add('h2','Intentos anteriores conservados',steps);for(const attempt of d.previous_attempts){if(attempt.status==='accepted_partial_not_completed')add('p','Reparto parcial anterior: la mano no se completó en esa sesión.',steps);add('a',attempt.file,steps).href='batches/'+batch+'/'+attempt.file;}}
}
main().catch(err=>document.querySelector('#summary').textContent=err.message);
</script>'''
    publish(ROOT/'playngo/round.html',page('Play’n GO · Ronda',viewer))
    from provider_reports import render_hub
    render_hub()
if __name__=='__main__':render()
