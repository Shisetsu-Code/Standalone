"""Provider-separated ELK reports with every native RESULT displayed separately."""
from collections import Counter
from html import escape as e
import argparse,hashlib,json
from pathlib import Path
from provider_reports import page,publish
from elk_paths import batch_path,catalog_slice,BATCHES

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'elk/batches/1-100'
def read(path,default):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default

def current_audit(batch='1-100'):
    FOLDER=batch_path(batch)
    audit=read(FOLDER/'audit.json',{})
    for name,value in audit.get('input_hashes',{}).items():
        p=ROOT/name
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=value:return {}
    return audit if audit.get('input_hashes') else {}

def hub_card():
    rows=[];links=[];audits=[]
    for batch in BATCHES:
        folder=batch_path(batch)
        if not (folder/'catalog.json').exists():continue
        rows+=read(folder/'rounds.json',[]);audits.append(current_audit(batch))
        links.append('<a href="elk/batches/'+batch+'/index.html">Lote '+batch.replace('-', '–')+'</a>')
    normal=len({r['slug'] for r in rows if r['mode']=='DEF' and r.get('status')=='completed'})
    modes=sum(r['mode']!='DEF' and r.get('status')=='completed' for r in rows)
    return '<section class="card"><h2>ELK Studios</h2><strong>'+str(normal)+' / 159</strong><p>Fichas con tirada normal · '+str(modes)+' pruebas de compras y modos</p><p>'+('Auditoría completa' if audits and all(a.get('passed') for a in audits) else 'Ver cobertura y pendientes en los informes')+'</p>'+' · '.join(links)+'<p><a href="elk/index.html">Catálogo ELK</a></p></section>'


def render(batch='1-100'):
    FOLDER=batch_path(batch);label=batch.replace('-', '–')
    catalog=read(ROOT/'elk/catalog.json',[]);scoped=read(FOLDER/'catalog.json',catalog_slice(batch));inv={r['slug']:r for r in read(FOLDER/'inventory.json',[])};rows=read(FOLDER/'rounds.json',[]);audit=current_audit(batch)
    completed=[r for r in rows if r.get('status')=='completed'];normal=len({r['slug'] for r in completed if r['mode']=='DEF'});modes=sum(r['mode']!='DEF' for r in completed);steps=sum(r.get('native_results',0) for r in completed)
    expected=sum(len(r.get('controls',[])) for r in inv.values());pending=sum(r.get('status')=='needs_review' for r in rows)
    body='<nav><a href="../../../providers.html">Proveedores</a> · <a href="../../index.html">Catálogo ELK</a> · <a href="rounds.json">Resultados JSON</a> · <a href="inventory.json">Modos publicados</a> · <a href="audit.json">Auditoría</a></nav><h1>ELK Studios · Lote '+label+'</h1>'
    expected_xiter=sum(c['mode']!='DEF' for item in inv.values() for c in item.get('controls',[]))
    body+='<div class="stats"><section class="card"><strong>'+str(normal)+' / '+str(len(scoped))+'</strong>Fichas con tirada normal</section><section class="card"><strong>'+str(modes)+' / '+str(expected_xiter)+'</strong>Compras y modos</section><section class="card"><strong>'+str(len(completed))+' / '+str(expected)+'</strong>Pruebas con variantes incluidas</section><section class="card"><strong>'+str(steps)+'</strong>Pasos internos registrados</section></div>'
    session_policy='Las pruebas ordinarias usan sesiones nuevas; Boss conserva una sesión con progreso nativo.' if read(FOLDER/'blocked-variants.json',{}).get('status')=='completed' else 'Cada entrada usa una sesión nueva.'
    body+='<p>Pruebas en los demos oficiales con saldo ficticio. '+session_policy+' Se usa el precio mínimo publicado para cada modo. Los pasos de cascadas y bonos se muestran por separado dentro de cada ronda.</p>'
    body+='<p>'+str(len(scoped))+' fichas del catálogo corresponden a '+str(len({g['id'] for g in scoped}))+' identificadores de demo.</p>'
    if any(g.get('shared_demo_with') for g in scoped):body+='<p>Pirots 4, Inferno y Frozen Fury enlazan al mismo demo con selector de variantes; se conserva la relación en el detalle.</p>'
    status='Auditoría completa: todas las pruebas y saldos coinciden con las respuestas nativas.' if audit.get('passed') else ('Auditoría parcial: '+str(audit.get('verified_cases',0))+' pruebas verificadas; quedan '+str(len(audit.get('problems',[])))+' incidencias por resolver.' if audit else 'Recorrido y verificación en proceso.')
    body+='<p class="'+('ok' if audit.get('passed') else 'pending')+'">'+status+'</p>'
    if pending:body+='<p class="pending">'+str(pending)+' solicitudes requieren revisión. Se muestran con su error y no cuentan como completadas.</p>'
    if (FOLDER/'blocked-variants.json').exists():
        if read(FOLDER/'blocked-variants.json',{}).get('status')=='completed':body+='<p class="ok">Pirots 5 · Boss: seis modos completados después de reunir los nueve tokens mediante el progreso nativo del demo. <a href="../../boss.html">Ver recorrido y desbloqueo</a>.</p>'
        else:body+='<p class="pending">Pirots 5 · Boss: el cliente oficial exige reunir nueve tokens antes de desbloquear esta variante. <a href="../../boss.html">Ver recorrido en curso</a> · <a href="blocked-variants.json">Evidencia y condiciones</a>.</p>'
    body+='<input placeholder="Buscar juego, modo o variante…" oninput="document.querySelectorAll(\'tbody tr.game\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))"><table><thead><tr><th>Juego</th><th>Modos publicados</th><th>Completadas</th><th>Detalles</th></tr></thead><tbody>'
    for game in scoped:
        cases=sorted([r for r in rows if r['slug']==game['slug']],key=lambda r:r['case']);controls=inv.get(game['slug'],{}).get('controls',[]);done=sum(r.get('status')=='completed' for r in cases)
        detail='<details><summary>Ver '+str(len(cases))+' pruebas</summary>'
        for row in cases:
            label=('Normal' if row['kind']=='normal' else 'Variante normal' if row['kind']=='variant' else 'Modo '+row['mode'])+(' · '+row['control']['variant'] if row.get('control',{}).get('variant') else '')
            detail+='<p><a href="../../round.html?batch='+batch+'&amp;case='+e(row['case'])+'">'+e(label)+'</a> · '+('Conciliada' if row.get('status')=='completed' else 'Revisar' if row.get('status')=='needs_review' else 'En proceso')
            if row.get('status')=='completed':detail+=' · '+e(row['cost'])+' EUR · '+str(row['native_results'])+' pasos'
            if row.get('error'):detail+='<br><small>'+e(row['error'])+'</small>'
            detail+='</p>'
        detail+='</details>'
        note='<br><small>Mismo demo que '+e(game['shared_demo_with'])+'</small>' if game.get('shared_demo_with') else ''
        body+='<tr class="game"><td>'+e(game['name'])+note+'</td><td>'+str(len(controls))+'</td><td>'+str(done)+' / '+str(len(controls))+'</td><td>'+detail+'</td></tr>'
    publish(FOLDER/'index.html',page('ELK Studios · Lote '+label,body+'</tbody></table>'))
    membership={g['slug']:b for b in BATCHES if (batch_path(b)/'catalog.json').exists() for g in catalog_slice(b)}
    nav=' · '.join('<a href="batches/'+b+'/index.html">Lote '+b.replace('-', '–')+'</a>' for b in BATCHES if (batch_path(b)/'catalog.json').exists())
    catbody='<nav><a href="../providers.html">Proveedores</a> · '+nav+'</nav><h1>ELK Studios · '+str(len(catalog))+' fichas</h1><p>'+str(len({g['id'] for g in catalog}))+' identificadores de demo oficiales. '+str(len(membership))+' fichas incluidas en los informes; '+str(len(catalog)-len(membership))+' sin recorrer.</p><table><tr><th>#</th><th>Juego</th><th>Estado</th><th>Ficha oficial</th></tr>'
    for g in catalog:
        b=membership.get(g['slug'])
        state='<a href="batches/'+b+'/index.html">Lote '+b.replace('-', '–')+'</a>' if b else 'Pendiente'
        catbody+='<tr><td>'+str(g['ordinal'])+'</td><td>'+e(g['name'])+'</td><td>'+state+'</td><td><a href="'+e(g['details_url'])+'">Fuente</a></td></tr>'
    publish(ROOT/'elk/index.html',page('ELK Studios · Catálogo',catbody+'</table>'))
    viewer='''<nav><a id="back" href="batches/1-100/index.html">Volver al lote ELK</a> · <a href="../providers.html">Proveedores</a></nav><h1 id="title">Ronda ELK</h1><div id="summary"></div><h2>Pasos internos de la ronda</h2><p>Cada RESULT del proveedor ocupa una fila. El total acumulado no se suma para calcular el premio. Los formatos antiguos sin importes por paso muestran sus valores nativos en monedas.</p><table><thead><tr><th>Paso</th><th>Modo nativo</th><th>Premio del paso</th><th>Acumulado</th><th>Datos</th></tr></thead><tbody id="steps"></tbody></table><h2>Mensajes de la sesión</h2><div id="messages"></div><script>
const add=(tag,text,parent)=>{const node=document.createElement(tag);node.textContent=text;parent.append(node);return node};
async function main(){const query=new URLSearchParams(location.search),batch=query.get('batch')||'1-100',id=query.get('case');if(!['1-100','101-159'].includes(batch))throw Error('Lote no válido');document.querySelector('#back').href='batches/'+batch+'/index.html';if(!/^[a-zA-Z0-9_-]+$/.test(id||''))throw Error('Ronda no válida');const response=await fetch('batches/'+batch+'/traces/'+encodeURIComponent(id)+'.json',{cache:'no-store'});if(!response.ok)throw Error('Ronda no encontrada');const d=await response.json(),r=d.summary;document.querySelector('#title').textContent=r.name+' · '+r.mode+(r.variant?' · '+r.variant:'');const summary=document.querySelector('#summary');add('p',r.status==='completed'?'Cerrada · saldo conciliado':'Pendiente de revisión',summary);if(r.cost)add('p','Entrada: '+r.cost+' EUR · Premio total: '+r.win+' EUR · Saldo: '+r.balance_before+' → '+r.balance_after+' EUR',summary);if(r.error)add('p',r.error,summary);if(d.campaign){const campaignLink=add('a','Ver recorrido de desbloqueo y sesión completa',summary);campaignLink.href='boss.html?campaign='+encodeURIComponent(d.campaign);add('span',' · ',summary);}const link=add('a','Descargar evidencia JSON',summary);link.href='batches/'+batch+'/traces/'+encodeURIComponent(id)+'.json';for(const step of d.results||[]){const tr=add('tr','',document.querySelector('#steps'));add('td',String(step.step+1),tr);add('td',step.mode||((step.attributes.freespin??step.attributes.freespins)==='0'?'Normal (formato clásico)':'Sin etiqueta'),tr);add('td',step.attributes.winamount??step.attributes.amount??(step.attributes.win!==undefined?step.attributes.win+' monedas':'—'),tr);add('td',step.attributes.amounttotal??(step.attributes.wintotal!==undefined?step.attributes.wintotal+' monedas':'—'),tr);const td=add('td','',tr),details=add('details','',td);add('summary','Ver XML del paso',details);add('pre',step.xml,details);}for(const message of d.trace){const details=add('details','',document.querySelector('#messages'));add('summary',message.method+' · HTTP '+(message.http_status??'sin respuesta'),details);add('pre',message.request,details);add('pre',message.response||'Sin respuesta XML válida',details);}}
main().catch(error=>document.querySelector('#summary').textContent=error.message);
</script>'''
    publish(ROOT/'elk/round.html',page('ELK · Ronda paso a paso',viewer))
    from provider_reports import render_hub
    render_hub()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',choices=list(BATCHES),default='1-100');args=parser.parse_args();render(args.batch)
