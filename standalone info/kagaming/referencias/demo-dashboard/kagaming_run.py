"""Sequential, resumable normal-demo verification. Unknown modes stop for review."""
import json,time,html,argparse
from pathlib import Path
import requests
from kagaming_client import DemoClient,minimum_profile,mode_profiles,position_for_step,save,validate_family,PRIVATE,NativeDemoError
from kagaming_core import sanitize,reconcile,needs_continuation
from kagaming_layout import batch_folder,batch_name,scope_policy,is_excluded
from kagaming_progress import validate_progress

ROOT=Path(__file__).resolve().parent
BATCH=batch_folder()

def existing_entries(folder):
    return {d['game']:d for p in Path(folder).glob('*-normal.json') for d in [json.loads(p.read_text(encoding='utf8'))]}

def verified_count(entries):
    return sum(d.get('status')=='verified' and d.get('wallet_check')=='match' for d in entries.values())

def can_defer_preflight(error,entry_started,unresolved):
    return not entry_started and not unresolved and error in {'family_protocol_requires_review','unreviewed_game_cost_formula','unreviewed_purchase_price','unreviewed_price_table','unreviewed_hotcoin_menu'}

def compact_status(campaign,normal,special,audit,exceptions):
    page='''<!doctype html><html lang="es"><meta charset="utf-8"><title>KA Gaming · Estado</title><style>body{font:20px system-ui;background:#101827;color:#e2e8f0;max-width:900px;margin:60px auto;padding:24px}section{background:#17243a;padding:24px;border-radius:16px;margin:20px 0}a{color:#7dd3fc}strong{font-size:30px}small{color:#a8b7cc}</style><h1>KA Gaming · Estado de las pruebas</h1>'''
    page+=f'<section><strong id="counts">{normal} normales · {special} variantes especiales</strong><p id="audit">Auditoría: {len(audit["cases"])} casos · '+('correcta' if audit['passed'] else 'requiere revisión')+'</p><small>Máximo un juego cada dos minutos. Saldo ficticio de la demo.</small></section>'
    page+='<p id="scope">'+str(campaign.get('excluded_games',0))+' juegos de caza/pesca excluidos.</p><section><h2>Estado actual</h2><p id="state">'+html.escape(campaign['status'])+'</p><p>Los casos incompletos o rechazados se conservan aparte. Los detalles muestran cada tirada interna del bono.</p></section><a href="index.html">Detalles por juego y modo</a> · <a href="audit.json">Auditoría</a>'
    page+='''<script>async function update(){try{const c=await(await fetch('campaign.json',{cache:'no-store'})).json();document.querySelector('#scope').textContent=(c.excluded_games||0)+' juegos de caza/pesca excluidos.';document.querySelector('#counts').textContent=c.verified_normal+' normales · '+c.verified_special+' variantes especiales';document.querySelector('#state').textContent=c.status+(c.game?' · '+c.game:'')+(c.mode?' · '+c.mode:'');const a=await(await fetch('audit.json',{cache:'no-store'})).json();document.querySelector('#audit').textContent='Auditoría: '+a.cases.length+' casos · '+(a.passed?'correcta':'requiere revisión')}catch(e){document.querySelector('#state').textContent='No se pudo actualizar el estado local'}}setInterval(update,5000);update();</script></html>'''
    if campaign.get('slots_only'):
        page=page.replace(str(normal)+' normales',str(normal)+' slots')
        page=page.replace('juegos de caza/pesca excluidos.','juegos que no son slots, documentados por separado.')
        page=page.replace("c.verified_normal+' normales", "c.verified_normal+' slots")
        page=page.replace('<a href="index.html">Detalles por juego y modo</a>','<a href="index.html">Slots: detalles por juego y modo</a> · <a href="non-slots.html">Lista separada: no slots</a>')
    return page

def report(campaign):
    from kagaming_audit import run as audit_recorded_cases
    audit=audit_recorded_cases()
    entries=existing_entries(BATCH/'traces');catalog=json.loads((BATCH/'catalog.json').read_text(encoding='utf8'))
    policy=scope_policy(BATCH);excluded={g['id'] for g in catalog if is_excluded(g,policy)}
    slots_only=policy.get('included_game_types')==['slots']
    entries={gid:record for gid,record in entries.items() if gid not in excluded}
    deferred=json.loads((BATCH/'deferred.json').read_text(encoding='utf8')) if (BATCH/'deferred.json').exists() else {}
    specials=[(p,json.loads(p.read_text(encoding='utf8'))) for p in (BATCH/'traces').glob('*.json') if not p.name.endswith('-normal.json')]
    specials=[(p,d) for p,d in specials if d.get('game') not in excluded]
    special_count=sum(d.get('status')=='verified' and d.get('wallet_check')=='match' for p,d in specials)
    save(BATCH/'campaign.json',dict(campaign,batch=batch_name(),slots_only=slots_only,verified_normal=verified_count(entries),verified_special=special_count,deferred_games=len(deferred),total_games=len(catalog),eligible_games=len(catalog)-len(excluded),excluded_games=len(excluded),minimum_interval_seconds=120))
    rows=[]
    for g in catalog:
        if slots_only and g['id'] in excluded:continue
        e=entries.get(g['id'],{});status={'verified':'Normal verificada','rejected_native':'Demo rechazó la entrada · revisar','needs_review':'Requiere revisión','started':'En curso'}.get(e.get('status'),'Pendiente')
        if g['id'] in excluded:status='Excluido por pedido del usuario · caza/pesca'
        if g['id'] in deferred:status+=' · protocolo pendiente'
        detail=f'<a href="traces/{g["id"]}-normal.json">Detalle nativo</a>' if e else ''
        for p,d in specials:
            if d.get('game')==g['id']:
                label=d.get('profile',{}).get('label') or (('Antebet '+str(d.get('atb'))) if d.get('mode')=='ante' else ('Compra '+str(d.get('atb') or 1)))
                label=label.replace('Lantern ','Farol ').replace('Special','Especial')
                detail+=f' · <a href="traces/{p.name}">{html.escape(label)} · {html.escape(d["status"])}</a>'
        completed=sum(d.get('status')=='verified' for p,d in specials if d.get('game')==g['id'])
        mode_label='Detectados · pendientes' if g.get('supportsBuyFeature') else 'Sin modos adicionales identificados'
        try:
            src=(ROOT/'kagaming/reference'/(g['id'].lower()+'.js')).read_text(encoding='utf8')
            native=json.loads((BATCH/'initializations'/(g['id']+'.json')).read_text(encoding='utf8'))
            expected=len(mode_profiles(native,src,g.get('supportsBuyFeature',False)))-1
            mode_label=str(completed)+'/'+str(expected)+' verificados' if expected else 'Sin modos adicionales identificados'
        except (OSError,ValueError,KeyError):pass
        if g['id'] in excluded:mode_label='Fuera del recorrido'
        rows.append('<tr>'+''.join('<td>'+str(x)+'</td>' for x in (g['ordinal'],html.escape(g['name']),g['gameType'],status,mode_label,detail))+'</tr>')
    page='''<!doctype html><html lang="es"><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>KA Gaming · Pruebas demo</title><style>body{background:#101827;color:#e2e8f0;font:16px system-ui;margin:35px}a{color:#7dd3fc}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #334155}small{color:#94a3b8}</style><h1>KA Gaming · Lote __BATCH__</h1>'''
    page=page.replace('__BATCH__',batch_name().replace('-','–'))
    if deferred:page+='<p>'+str(len(deferred))+' juegos con protocolo pendiente de revisión · <a href="deferred.json">Ver pendientes</a></p>'
    if excluded:page+='<p>'+str(len(excluded))+(' juegos que no son slots, fuera de prioridad. <a href="non-slots.html">Lista y documentación separada</a>.' if slots_only else ' juegos de caza/pesca excluidos por pedido del usuario.')+'</p>'
    page+=f'<p><strong>{verified_count(entries)}/{len(catalog)-len(excluded)} tiradas normales verificadas</strong> · {special_count} variantes especiales verificadas · catálogo completo: 1.049 juegos.</p><p>Ritmo máximo: un juego cada dos minutos. Estado: {html.escape(campaign["status"])}.</p><p>Los modos no verificados siguen pendientes. Los detalles conservan cada tirada interna del bono y las respuestas rechazadas por separado.</p><p><a href="audit.json">Auditoría de los casos registrados</a> · <a href="campaign.json">Estado de ejecución</a> · <a href="catalog.json">Catálogo del lote</a> · <a href="../../../providers.html">Proveedores</a></p><table><thead><tr><th>#</th><th>Juego</th><th>Familia</th><th>Normal</th><th>Modos especiales</th><th>Evidencia</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>'
    if slots_only:
        separate=''.join('<tr><td>'+str(g['ordinal'])+'</td><td>'+html.escape(g['name'])+'</td><td>'+html.escape(g['gameType'])+'</td><td>Separado · sin más pruebas</td></tr>' for g in catalog if g['id'] in excluded)
        page=page.replace('</table></html>','</table><h2>Lista separada: no slots</h2><p>Se conservan en el catálogo y sus historiales previos. <a href="non-slots.html">Ver documentación y casos conservados</a>.</p><table><tr><th>#</th><th>Juego</th><th>Tipo</th><th>Estado</th></tr>'+separate+'</table></html>')
        page=page.replace('tiradas normales verificadas','slots verificados')
    (BATCH/'index.html').write_text(page,encoding='utf8')
    (BATCH/'status.html').write_text(compact_status(dict(campaign,slots_only=slots_only,excluded_games=len(excluded),eligible_games=len(catalog)-len(excluded)),verified_count(entries),special_count,audit,[]),encoding='utf8')

def pending_profiles(profiles,records):
    for key,record in records.items():
        if record.get('status')!='verified':raise ValueError('previous_mode_requires_review:'+key)
    pending=[]
    for profile in profiles:
        previous=records.get(profile['key'])
        if previous is None:pending.append(profile)
        elif previous.get('status')!='verified':raise ValueError('previous_mode_requires_review:'+profile['key'])
    return pending

def reviewed_normal_rejection(records):
    normal=records.get('normal',{})
    if normal.get('reviewed_native_rejection') is not True:return False
    if normal.get('status')!='rejected_native':raise ValueError('reviewed_rejection_has_unresolved_status')
    pending_profiles([],{key:record for key,record in records.items() if key!='normal'})
    return True

def execute_step(client,profile,previous,journal):
    if previous is not None:
        if previous.get('v') is not True or type(previous.get('sid')) is not int or previous['sid']<0 or not isinstance(previous.get('tid'),str) or not previous['tid']:raise ValueError('unconfirmed_previous_native_result')
    module={'HomeRunDerby':'kagaming_interactive','BonusPoker':'kagaming_interactive','ChickenQuest':'kagaming_chicken','PenaltyShootout':'kagaming_penalty','PhilosopherRoulette':'kagaming_philosopher'}.get(profile.get('game_id'))
    if module:
        from importlib import import_module
        api=import_module(module)
        client.sequence+=1
        sid=int(time.time()*1000)%2000000000+client.sequence
        plan=api.initial_request(profile,sid) if previous is None else api.next_request(profile,previous,sid=sid)
        if plan is None:raise ValueError('request_after_interactive_round_closed')
        return client.request(plan['path'],plan['body'],journal)
    from kagaming_bonus_pick import is_supported
    if previous and is_supported(client.gid) and previous.get('bpd'):
        from kagaming_bonus_pick import decision
        root=ROOT/'kagaming/reference'
        row=decision(client.gid,previous,(root/(client.gid.lower()+'.js')).read_bytes(),(root/'game.min.2090.js').read_bytes())
        if row['action']=='bonus_pick':
            return client.request('/kaga/command/bonusPick',{'gn':client.gid,'p':row['pick'],'sid':previous['sid']},journal)
        if row['action']=='closed':raise ValueError('request_after_bonus_round_closed')
    return client.spin(profile,journal,position=position_for_step(profile,previous))

def run(limit):
    catalog=json.loads((BATCH/'catalog.json').read_text(encoding='utf8'))
    deferred_path=BATCH/'deferred.json';deferred=json.loads(deferred_path.read_text(encoding='utf8')) if deferred_path.exists() else {}
    policy=scope_policy(BATCH);excluded={g['id']:{'game':g['id'],'family':g['gameType'],'reason':policy.get('reason','user_requested_skip_hunting_fishing'),'user_requested':True} for g in catalog if is_excluded(g,policy)}
    save(BATCH/'excluded.json',excluded)
    for gid in excluded:deferred.pop(gid,None)
    save(deferred_path,deferred)
    campaign={'status':'En ejecución','updated_at':time.time()};report(campaign)
    for game in catalog[:limit]:
        if is_excluded(game,policy):continue
        gid=game['id'];records={p.name[len(gid)+1:-5]:json.loads(p.read_text(encoding='utf8')) for p in (BATCH/'traces').glob(gid+'-*.json')}
        campaign.pop('mode',None);campaign.pop('error',None)
        entry_started=False;unresolved=any(r.get('status')!='verified' for r in records.values())
        source_path=ROOT/'kagaming/reference'/(gid.lower()+'.js')
        init_path=BATCH/'initializations'/(gid+'.json')
        try:
            if reviewed_normal_rejection(records):continue
            if records and source_path.exists() and init_path.exists():
                old_profiles=mode_profiles(json.loads(init_path.read_text(encoding='utf8')),source_path.read_text(encoding='utf8'),game.get('supportsBuyFeature',False))
                if not pending_profiles(old_profiles,records):
                    if gid in deferred:deferred.pop(gid);save(deferred_path,deferred)
                    continue
            elif any(d.get('status')!='verified' for d in records.values()):raise ValueError('previous_request_requires_review')
            if game['gameType']!='slots':
                if not source_path.exists():raise ValueError('family_protocol_requires_review')
                validate_family(game,source_path.read_bytes().decode('utf8'))
            while True:
                old=json.loads((PRIVATE/'cadence.json').read_text(encoding='utf8')) if (PRIVATE/'cadence.json').exists() else {}
                wait=120-(time.time()-old.get('last_started_at',0))
                if wait<=0:break
                campaign.update(status='Esperando intervalo de dos minutos',game=gid,updated_at=time.time());report(campaign);time.sleep(min(wait,10))
            campaign.update(status='Verificando demo y sus modos',game=gid,updated_at=time.time());report(campaign)
            client=DemoClient(gid);init=client.start();save(init_path,sanitize(init))
            url='https://gamesdemo.kaga88.com/res/js/2090/'+gid.lower()+'.js'
            response=requests.get(url,timeout=30);response.raise_for_status();source=response.content.decode('utf8');source_path.write_bytes(response.content)
            validate_family(game,source)
            profiles=mode_profiles(init,source,game.get('supportsBuyFeature',False));before=init['bl']
            for profile in pending_profiles(profiles,records):
                campaign.update(status='Verificando modo',game=gid,mode=profile['key'],updated_at=time.time());report(campaign)
                target=BATCH/'traces'/(gid+'-'+profile['key']+'.json')
                record={'game':gid,'mode':profile['kind'],'atb':profile['atb'],'status':'started','profile':profile,'steps':[],'created_at':time.time(),'session_group':client.folder.name}
                entry_started=True
                save(target,record)
                try:
                    for i in range(100):
                        time.sleep(2)
                        outgoing=dict(profile,atb=0) if i and profile.get('purchase_via_atb') else profile
                        previous=record['steps'][-1]['response']['md'] if i else None
                        step=execute_step(client,outgoing,previous,client.folder/(profile['key']+'-step-'+str(i)+'.json'))
                        record['steps'].append(sanitize(step));save(target,record)
                        validate_progress(profile,before,record['steps'])
                        if not needs_continuation(step['response']['md'],gid):break
                    else:raise ValueError('continuation_limit')
                    record.update(reconcile(before,profile['cost_native'],record['steps'],profile=profile),status='verified')
                    from kagaming_audit import audit_case
                    audit=audit_case(record)
                    if not audit['passed']:raise ValueError('independent_native_audit_failed:'+audit['error'])
                    save(target,record);before=record['balance_after_native']
                except Exception as error:
                    if isinstance(error,NativeDemoError):record['steps'].append(sanitize(error.record))
                    record.update(status='needs_review',error=str(error));save(target,record);raise
                campaign.update(status='Modo verificado',game=gid,mode=profile['key'],updated_at=time.time());report(campaign)
                print(json.dumps({'game':gid,'mode':profile['key'],'status':record['status'],'wallet_check':record['wallet_check']}),flush=True)
            if gid in deferred:deferred.pop(gid);save(deferred_path,deferred)
        except Exception as error:
            if can_defer_preflight(str(error),entry_started,unresolved):
                deferred[gid]={'game':gid,'family':game['gameType'],'reason':str(error),'status':'preflight_review_required','no_new_stake_sent':True};save(deferred_path,deferred)
                campaign.update(status='Protocolo pendiente; continuando con el siguiente juego',game=gid,error=str(error),updated_at=time.time());report(campaign)
                continue
            campaign.update(status='Detenido: revisar respuesta o protocolo',game=gid,error=str(error),updated_at=time.time());report(campaign);return
    campaign.update(status='Tramo recorrido; '+str(len(deferred))+' juegos requieren revisión de protocolo',updated_at=time.time());report(campaign)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=100);args=parser.parse_args();run(max(1,min(100,args.limit)))
