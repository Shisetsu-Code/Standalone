"""KA provider summary derived only from the current campaign and native audit."""
import json
from pathlib import Path
from kagaming_layout import BATCHES

ROOT=Path(__file__).resolve().parent


def hub_card(root=ROOT):
    normal=special=eligible=excluded=0;audited=True;links=[];snapshots=[]
    for name in BATCHES:
        folder=Path(root)/'kagaming/batches'/name
        if not (folder/'campaign.json').exists():continue
        campaign=json.loads((folder/'campaign.json').read_text(encoding='utf8'))
        audit=json.loads((folder/'audit.json').read_text(encoding='utf8'))
        snapshots.append((name,campaign,audit))
        n=campaign['verified_normal'];s=campaign['verified_special']
        normal+=n;special+=s;eligible+=campaign['eligible_games'];excluded+=campaign['excluded_games']
        audited=audited and audit.get('passed') is True and len(audit.get('cases',[]))==n+s
        links.append('<a href="kagaming/batches/'+name+'/index.html">Detalle por juego y modo · Lote '+name+'</a> · <a href="kagaming/batches/'+name+'/status.html">Estado</a>')
    state='Casos registrados auditados.' if audited else 'Auditoría pendiente de actualización.'
    if snapshots and snapshots[-1][1].get('slots_only'):
        name,c,a=snapshots[-1];n=c['verified_normal'];s=c['verified_special'];e=c['eligible_games']
        state='Casos de slots auditados.' if a.get('passed') is True and len(a.get('cases',[]))==n+s else 'Auditoría de slots en proceso.'
        history=''.join('<p>Histórico '+old+': '+str(data['verified_normal'])+' normales · '+str(data['verified_special'])+' variantes. <a href="kagaming/batches/'+old+'/index.html">Ver lote</a></p>' for old,data,_ in snapshots[:-1])
        return ('<section class="card"><h2>KA Gaming</h2><strong>'+str(n)+' / '+str(e)+'</strong><p>Slots verificados · Lote '+name+' · '+str(s)+' compras y variantes de slots. '+state+'</p>'+
                '<p><a href="kagaming/batches/'+name+'/index.html">Slots: detalles y modos</a> · <a href="kagaming/batches/'+name+'/status.html">Estado</a></p>'+
                '<p><a href="kagaming/batches/'+name+'/non-slots.html">'+str(c['excluded_games'])+' juegos que no son slots · lista separada</a></p>'+history+'</section>')
    return ('<section class="card"><h2>KA Gaming</h2><strong>'+str(normal)+' / '+str(eligible)+
            '</strong><p>Normales verificadas · '+str(special)+' variantes especiales. '+state+
            '</p><p>'+str(excluded)+' juegos de caza/pesca excluidos.</p>'+'<p>'+'</p><p>'.join(links)+'</p></section>')
