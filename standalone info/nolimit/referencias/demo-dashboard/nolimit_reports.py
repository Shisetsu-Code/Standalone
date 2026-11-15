"""Nolimit City stays separate from the other providers and their reports."""
from html import escape
import json
import hashlib
from pathlib import Path
from provider_reports import page,publish

ROOT=Path(__file__).resolve().parent/'nolimit'


def read(path,default):return json.loads(path.read_text(encoding='utf8')) if path.exists() else default

def audited_now(folder):
    audit=read(folder/'audit.json',{})
    if not audit.get('passed') or not audit.get('input_hashes'):return False
    return all((folder/name).exists() and hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest for name,digest in audit['input_hashes'].items())


def hub_card():
    if not (ROOT/'catalog.json').exists():return ''
    normal=buys=0;links=''
    for folder in sorted((ROOT/'batches').glob('*'),key=lambda p:int(p.name.split('-')[0])):
        n=sum(r['status']=='completed' and r.get('wallet_check')=='match' for r in read(folder/'rounds.json',[]))
        b=sum(r['status']=='completed' and r.get('wallet_check')=='match' for r in read(folder/'purchases.json',[]));normal+=n;buys+=b
        links+='<p><a href="nolimit/batches/'+folder.name+'/index.html">Lote '+folder.name+'</a> · '+str(n)+'/'+str(len(read(folder/'catalog.json',[])))+' normales · '+('Auditado' if audited_now(folder) else 'En proceso')+'</p>'
    return '<section class="card"><h2>Nolimit City</h2><strong>'+str(normal)+'</strong><p>Tiradas normales conciliadas · '+str(buys)+' compras y variantes</p>'+links+'<a href="nolimit/index.html">Catálogo de Nolimit City</a></section>'


def render(batch='1-100'):
    from provider_reports import render_hub
    folder=ROOT/'batches'/batch;folder.mkdir(parents=True,exist_ok=True)
    catalog=read(folder/'catalog.json',[]);inventory=read(folder/'inventory.json',[])
    rows=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])+read(folder/'choices.json',[])
    good=lambda r:r['status']=='completed' and r.get('wallet_check')=='match'
    normal=sum(r['kind']=='normal' and good(r) for r in rows);buys=sum(r['kind']=='purchase' and good(r) for r in rows)
    expected=sum(len(r.get('controls') or []) for r in inventory)
    matrix=read(folder/'choices-matrix.json',{}).get('summary',{});audited=audited_now(folder)
    body='<nav><a href="../../../providers.html">Todos los proveedores</a> · <a href="../../index.html">Catálogo de Nolimit City</a> · <a href="inventory.json">Inventario</a> · <a href="audit.json">Auditoría</a> · <a href="choices-matrix.json">Elecciones internas</a></nav><h1>Nolimit City · Juegos '+batch.replace('-','–')+'</h1><div class="stats">'
    menu_value=str(matrix['verified'])+' / '+str(matrix['options']) if matrix else 'Pendiente'
    for value,label in [(str(normal)+' / '+str(len(catalog)),'Tiradas normales'),(str(buys)+' / '+str(expected),'Compras y variantes'),(menu_value,'Opciones internas habilitadas observadas')]:body+='<div class="card"><strong>'+value+'</strong>'+label+'</div>'
    body+='</div><p>Sesiones nuevas oficiales FANPAGE_DEMO y saldo ficticio. Compras, activadores y apuestas laterales individuales en sus contextos publicados. Cada tirada gratis y decisión queda dentro de su ronda.</p><p class="'+('ok' if audited else 'pending')+'">'+('Auditoría completa: cierre y saldo verificados.' if audited else 'Pruebas en proceso; los casos pendientes no cuentan como aprobados.')+'</p>'
    if any(g['code']=='DuckHunters2' for g in catalog):body+='<p>Duck Hunters 2: EXTRA_SPIN conserva las opciones NO, HALF y SAME (botón NORMAL) con su coste nativo. SAME solo se habilita cuando el premio acumulado alcanza el coste publicado.</p>'
    examples=[]
    for option in ('HALF','SAME'):
        example=next((r for r in rows if r['code']=='DuckHunters2' and good(r) and any(c['selected']==option for c in r.get('choices',[]))),None)
        if example:examples.append('<a href="../../round.html?batch='+batch+'&case='+escape(example['case'])+'">Ver prueba de '+option+'</a>')
    if examples:body+='<p>'+' · '.join(examples)+'</p>'
    body+='<input placeholder="Buscar juego…" oninput="document.querySelectorAll(\'tbody tr\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))"><table><thead><tr><th>Juego</th><th>Normal</th><th>Controles publicados</th><th>Detalle</th></tr></thead><tbody>'
    for game in catalog:
        meta=next((r for r in inventory if r['code']==game['code']),{});cases=[r for r in rows if r['code']==game['code']]
        n=next((r for r in cases if r['kind']=='normal'),{});state='Conciliada' if n and good(n) else n.get('reason',meta.get('reason','Pendiente'))
        controls='<details><summary>'+str(len(meta.get('controls') or []))+' controles</summary>'+'<br>'.join(escape(c['control_id'])+' ×'+escape(c['multiplier']) for c in meta.get('controls') or [])+'</details>'
        detail='<details><summary>Ver '+str(len(cases))+' pruebas</summary>'
        for kind,title in [('normal','Normal'),('purchase','Compras y variantes'),('choice','Elecciones internas')]:
            group=[r for r in cases if r['kind']==kind]
            if not group:continue
            detail+='<details><summary>'+title+' ('+str(len(group))+')</summary>'
            for row in group:
                detail+='<p>'+escape(row.get('control_id') or row['case'])+' · '+('Saldo correcto' if good(row) else escape(row.get('reason',row['status'])))+' · <a href="../../round.html?batch='+batch+'&case='+escape(row['case'])+'">Ver ronda paso a paso</a> · <a href="traces/'+escape(row['case'])+'.json">JSON</a></p>'
            detail+='</details>'
        body+='<tr><td>'+escape(game['name'])+'<br><small>'+escape(game['code'])+'</small></td><td>'+escape(state)+'</td><td>'+controls+'</td><td>'+detail+'</details></td></tr>'
    publish(folder/'index.html',page('Nolimit City · Lote '+batch,body+'</tbody></table>'))
    membership={};links=[]
    for f in sorted((ROOT/'batches').glob('*'),key=lambda p:int(p.name.split('-')[0])):
        membership.update({g['code']:f.name for g in read(f/'catalog.json',[])});links.append('<a href="batches/'+f.name+'/index.html">Lote '+f.name+'</a>')
    catalog=read(ROOT/'catalog.json',[])
    body='<nav><a href="../providers.html">Proveedores</a> · '+' · '.join(links)+'</nav><h1>Nolimit City · '+str(len(catalog))+' juegos publicados</h1><p>Catálogo completo capturado; orden descendente del identificador CMS. <a href="upcoming.json">Próximos lanzamientos separados</a>.</p><table><tr><th>Juego</th><th>Lote</th><th>Fuente</th></tr>'
    for game in catalog:body+='<tr><td>'+escape(game['name'])+'</td><td>'+membership.get(game['code'],'Pendiente')+'</td><td><a href="'+escape(game['details_url'])+'">Sitio oficial</a></td></tr>'
    publish(ROOT/'index.html',page('Nolimit City · Catálogo',body+'</table>'));render_hub()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--batch',default='1-100');render(p.parse_args().batch)
