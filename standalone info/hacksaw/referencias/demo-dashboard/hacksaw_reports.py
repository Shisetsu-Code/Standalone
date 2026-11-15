"""Provider-isolated static reports for Hacksaw native demo traces."""
from html import escape
import json
from pathlib import Path
from provider_reports import page,publish
from hacksaw_contracts import mode_cases

ROOT=Path(__file__).resolve().parent/'hacksaw'


def read(path,default):
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else default


def hub_card():
    if not (ROOT/'catalog.json').exists():return ''
    folders=sorted((ROOT/'batches').glob('*'),key=lambda p:int(p.name.split('-')[0]))
    normal=purchases=0;links=''
    for folder in folders:
        n=sum(r.get('status')=='completed' and r.get('wallet_check')=='match' for r in read(folder/'rounds.json',[]))
        p=sum(r.get('status')=='completed' and r.get('wallet_check')=='match' for r in read(folder/'purchases.json',[]))
        normal+=n;purchases+=p
        links+='<p><a href="hacksaw/batches/'+folder.name+'/index.html">Lote '+folder.name+'</a> · '+str(n)+'/'+str(len(read(folder/'catalog.json',[])))+' normales · '+('Auditado' if read(folder/'audit.json',{}).get('passed') else 'En proceso')+'</p>'
    return '<section class="card"><h2>Hacksaw Gaming</h2><strong>'+str(normal)+'</strong><p>Tiradas normales conciliadas · '+str(purchases)+' compras, activadores y modos</p>'+links+'<a href="hacksaw/index.html">Catálogo de Hacksaw</a></section>'


def render(batch='1-100'):
    from provider_reports import render_hub
    folder=ROOT/'batches'/batch;folder.mkdir(parents=True,exist_ok=True)
    catalog=read(folder/'catalog.json',[]);inventory=read(folder/'inventory.json',[])
    rows=read(folder/'rounds.json',[])+read(folder/'purchases.json',[])+read(folder/'choices.json',[])
    normal=sum(r.get('kind')=='normal' and r.get('status')=='completed' and r.get('wallet_check')=='match' for r in rows)
    buys=sum(r.get('kind')=='purchase' and r.get('status')=='completed' and r.get('wallet_check')=='match' for r in rows)
    expected=sum(len(r.get('bonus_games') or []) for r in inventory)+sum(len(mode_cases(g)) for g in catalog)
    menus=read(folder/'choices-matrix.json',{}).get('summary',{})
    audited=read(folder/'audit.json',{}).get('passed',False)
    body='<nav><a href="../../../providers.html">Todos los proveedores</a> · <a href="../../index.html">Catálogo de Hacksaw</a> · <a href="inventory.json">Inventario</a> · <a href="audit.json">Auditoría</a> · <a href="choices-matrix.json">Elecciones internas</a></nav><h1>Hacksaw · Juegos '+batch.replace('-','–')+'</h1><div class="stats">'
    for value,label in [(str(normal)+' / '+str(len(catalog)),'Tiradas normales'),(str(buys)+' / '+str(expected),'Compras, activadores y modos'),(str(menus.get('verified',0))+' / '+str(menus.get('options',0)),'Opciones internas observadas')]:
        body+='<div class="card"><strong>'+value+'</strong>'+label+'</div>'
    body+='</div><p>Sesiones nuevas de las demos oficiales, con saldo ficticio. Todas las entradas distintas de la tirada normal cuentan como compras; se conserva el identificador nativo de cada activador.</p><p class="'+('ok' if audited else 'pending')+'">'+('Auditoría completa: cierre de ronda y saldo verificados.' if audited else 'Pruebas en proceso. Los casos pendientes no cuentan como aprobados.')+'</p><input placeholder="Buscar juego…" oninput="document.querySelectorAll(\'tbody tr\').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))"><table><thead><tr><th>Juego</th><th>Normal</th><th>Compras / activadores publicados</th><th>Detalle</th></tr></thead><tbody>'
    for game in catalog:
        meta=next((r for r in inventory if r['id']==game['id']),{})
        cases=[r for r in rows if r['id']==game['id']]
        n=next((r for r in cases if r.get('kind')=='normal'),{})
        state='Conciliada' if n.get('status')=='completed' and n.get('wallet_check')=='match' else n.get('reason',meta.get('reason','Pendiente'))
        detail='<details><summary>Ver '+str(len(cases))+' pruebas</summary>'
        for kind,title in [('normal','Normal'),('purchase','Compras y activadores'),('choice','Elecciones internas')]:
            selected=[r for r in cases if r.get('kind')==kind]
            if not selected:continue
            detail+='<details><summary>'+title+' ('+str(len(selected))+')</summary>'
            for row in selected:
                label=row.get('label') or row.get('bonus_id') or 'normal'
                detail+='<p>'+escape(label)+' · '+('Saldo correcto' if row.get('status')=='completed' and row.get('wallet_check')=='match' else escape(row.get('reason',row['status'])))+' · <a href="../../round.html?batch='+batch+'&case='+row['case']+'">Ver ronda paso a paso</a> · <a href="traces/'+row['case']+'.json">JSON</a></p>'
            detail+='</details>'
        controls='<br>'.join(escape(c['bonusGameId'])+' ×'+escape(str(c['betCostMultiplier'])) for c in meta.get('bonus_games') or []) or 'Sin compras publicadas'
        for mode in mode_cases(game):controls+='<br>'+escape(mode['label'])+' ×1'
        body+='<tr><td>'+escape(game['name'])+'<br><small>ID '+game['id']+'</small></td><td>'+escape(state)+'</td><td>'+controls+'</td><td>'+detail+'</details></td></tr>'
    publish(folder/'index.html',page('Hacksaw · Lote '+batch,body+'</tbody></table>'))
    membership={}
    links=[]
    for f in sorted((ROOT/'batches').glob('*'),key=lambda p:int(p.name.split('-')[0])):
        membership.update({r['id']:f.name for r in read(f/'catalog.json',[])})
        links.append('<a href="batches/'+f.name+'/index.html">Lote '+f.name+'</a>')
    body='<nav><a href="../providers.html">Proveedores</a> · '+' · '.join(links)+'</nav><h1>Hacksaw · '+str(len(read(ROOT/'catalog.json',[])))+' juegos</h1><table><tr><th>Juego</th><th>Lote</th><th>Fuente</th></tr>'
    for game in read(ROOT/'catalog.json',[]):body+='<tr><td>'+escape(game['name'])+'</td><td>'+membership.get(game['id'],'Pendiente')+'</td><td><a href="'+escape(game['details_url'])+'">Ficha oficial</a></td></tr>'
    publish(ROOT/'index.html',page('Hacksaw · Catálogo',body+'</table>'));render_hub()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--batch',default='1-100');render(p.parse_args().batch)
