"""Publish sanitized progress from archived, independently checked demo roots."""
import json,hashlib,html
from datetime import datetime,timezone
from har_probe import ROOT
from catalog_network import durable

def main():
    now=datetime.now(timezone.utc).isoformat()
    results=[json.loads((ROOT/f'results/first-{mode}.json').read_text(encoding='utf8')) for mode in ('normal','purchase')]
    results.extend(json.loads(p.read_text(encoding='utf8')) for p in (ROOT/'results').glob('rp_*-normal.json'))
    results.extend(json.loads(p.read_text(encoding='utf8')) for p in (ROOT/'results').glob('rp_*-purchase-*.json'))
    verified={r['game'] for r in results}
    for r in results:
        if not r['finished'] or not all(s['wallet_matches'] and s['expected_balance']==s['server_balance'] for s in r['steps']):raise ValueError('unsettled_root')
    summary={'updated_at':now,'status':'official_games_processing','verified_games':len(verified),'verified_modes':len(results),
        'new_gameplay_requests_sent':sum(len(r['steps']) for r in results),'current_roots':[],'uncertain_roots':[],
        'completed_games':[{'game':'rp_222','title':'Mad Hit Diamonds Extreme','modes':['normal','buy_feature:respin'],
                            'wallet_checks':15,'transport':'isolated_native_HTTP','native_protocol':2,'native_math':2025093096,
                            'evidence':['results/first-normal.json','results/first-purchase.json']}],
        'sessions_from_har_reused':0,'real_funds_used':False}
    links=json.loads((ROOT/'catalogs/official-links.json').read_text(encoding='utf8'))
    for native in sorted(verified-{'rp_222'}):
        game=next(g for g in links['games'] if g.get('native_identity')==native)
        binding=json.loads((ROOT/('results/'+native+'-binding.json')).read_text(encoding='utf8'))
        modes=[r['mode'] for r in results if r['game']==native]
        expected_modes=['normal']+(['buy_feature:'+p['buyFeatureType'] for p in binding.get('declared_purchases',[])] if binding.get('buy_feature_available') else [])
        summary['completed_games'].append({'game':native,'title':game['title'],'modes':modes,
            'buy_feature_available':binding['buy_feature_available'],'native_math':binding['math'],
            'all_server_offered_purchase_modes_closed':set(expected_modes).issubset(modes),
            'mode_coverage':'native normal and listed purchase variants only; no unoffered modes inferred',
            'evidence':['results/'+native+'-normal.json','results/'+native+'-binding.json']+[
                p.relative_to(ROOT).as_posix() for p in (ROOT/'results').glob(native+'-purchase-*.json')]})
    for p in (ROOT/'results').glob('rp_*-root-state.json'):
        state=json.loads(p.read_text(encoding='utf8'))
        if state['state']!='closed':summary['current_roots'].append(state)
    batch_file=ROOT/'results/batch-progress.json'
    batch=json.loads(batch_file.read_text(encoding='utf8')) if batch_file.exists() else {}
    summary['batch_state']=batch.get('state','not_started')
    summary['batch_pid']=batch.get('pid')
    summary['new_gameplay_requests_sent']=sum(1 for p in (ROOT/'private/live').glob('*/*.journal.json')
        if (meta:=json.loads(p.read_text(encoding='utf8'))).get('financial_action') and meta.get('state')=='received')
    if 'uncertain_financial_request' in batch.get('reason',''):summary['uncertain_roots'].append({'game':batch.get('current_game'),'reason':batch['reason']})
    durable(ROOT/'results/live-summary.json',summary)
    queue=[]
    for g in links['games']:
        native=g.get('native_identity');status='normal_and_declared_purchase_complete' if native=='rp_222' else ('pending_native_protocol' if g.get('public_demo_url') else 'upcoming_no_demo_link')
        if native in verified-{'rp_222'}:
            record=next(r for r in summary['completed_games'] if r['game']==native)
            status=('normal_and_declared_purchase_complete' if record['buy_feature_available'] else 'normal_verified_no_purchase_offered') if record['all_server_offered_purchase_modes_closed'] else 'normal_verified_purchases_pending'
        elif native in batch.get('games',{}) and native not in verified:status=batch['games'][native]['state']
        queue.append({**g,'processing_status':status})
    durable(ROOT/'results/game-processing-queue.json',{'updated_at':now,'official_entries':len(queue),'demo_links':179,'completed_games':len(verified),'remaining_linked_games':179-len(verified),'games':queue})
    monitoring=json.loads((ROOT/'results/monitoring.json').read_text(encoding='utf8'))
    monitoring.update({'last_local_check':now,'state':'official_games_processing','required_sources':['rubyplay'],
                       'deferred_sources':['slotcatalog','slotstemple'],'new_gameplay_requests_sent':summary['new_gameplay_requests_sent'],
                       'verified_games':len(verified),'verified_modes':len(results),'own_process_running':batch.get('state')=='running',
                       'batch_pid':batch.get('pid'),'batch_state':batch.get('state','not_started'),
                       'next_action':'Prepare '+next((g['native_identity'] for g in queue if g['processing_status']=='pending_native_protocol' and g.get('native_identity')),'no_pending_game')+'; use parameterized native scripts and review family actions before sending. Do not replay closed roots.',
                       'last_offline_finding':f'{len(verified)} games and {len(results)} settled modes; costs and payouts reconciled using native math. Coverage limited to declared session variants.',
                       'catalogue_fingerprint':hashlib.sha256((ROOT/'catalogs/official-links.json').read_bytes()).hexdigest()})
    durable(ROOT/'results/monitoring.json',monitoring)
    pending=[{k:g.get(k) for k in ('native_identity','title','public_demo_url','processing_status')}|
             {'client_class':batch.get('games',{}).get(g.get('native_identity'),{}).get('client_class'),
              'reason':batch.get('games',{}).get(g.get('native_identity'),{}).get('reason')}
             for g in queue if g.get('native_identity') not in verified]
    durable(ROOT/'results/batch-pending.json',{'updated_at':now,'batch_state':batch.get('state','not_started'),
            'pending_entries':len(pending),'games':pending})
    rows=[]
    for g in queue:
        url=g.get('public_demo_url');title=html.escape(g.get('title',''));native=html.escape(g.get('native_identity') or '—')
        link=f'<a href="{html.escape(url,quote=True)}" rel="noreferrer">Abrir demo</a>' if url else 'Sin enlace demo'
        status='Normal + compra verificadas' if g.get('native_identity')=='rp_222' else ('Pendiente de prueba' if url else 'Próximo lanzamiento')
        if g.get('native_identity') in verified-{'rp_222'}:
            record=next(r for r in summary['completed_games'] if r['game']==g['native_identity'])
            status='Normal + compras ofrecidas verificadas' if record['buy_feature_available'] and record['all_server_offered_purchase_modes_closed'] else ('Normal verificada; demo sin compra habilitada' if not record['buy_feature_available'] else 'Normal verificada; compras pendientes')
        elif g.get('native_identity') not in verified:
            status={'needs_contract':'Familia pendiente de revisión','needs_adapter':'Lectura del cliente pendiente',
                'needs_review':'Revisión pendiente','setup_failed':'No pudo inicializarse; sin reintentos',
                'preparing':'Preparando','processing':'Probando','uncertain':'Respuesta incierta; detenido'}.get(g['processing_status'],status)
        details=[]
        for case in [r for r in results if r['game']==g.get('native_identity')]:
            path=('first-normal.json' if case['mode']=='normal' else 'first-purchase.json') if case['game']=='rp_222' else (case['game']+'-normal.json' if case['mode']=='normal' else next(p.name for p in (ROOT/'results').glob(case['game']+'-purchase-*.json') if json.loads(p.read_text(encoding='utf8'))['mode']==case['mode']))
            label='Normal' if case['mode']=='normal' else 'Compra de bono'
            details.append(f'<a href="../results/{html.escape(path,quote=True)}">{label}: {len(case["steps"])} respuestas verificadas</a>')
        rows.append(f'<tr><td>{title}</td><td>{native}</td><td>{link}</td><td>{status}<br>{"<br>".join(details)}</td></tr>')
    page='<!doctype html><html lang="es"><meta charset="utf-8"><title>RubyPlay · enlaces y progreso</title><style>body{font:16px system-ui;margin:32px;background:#10151f;color:#e8eef8}table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #344054}a{color:#8ac5ff}</style><h1>RubyPlay · enlaces y progreso</h1><p>180 entradas oficiales · 179 demos enlazadas · 1 juego verificado · 178 pendientes. Sólo saldo ficticio.</p><p>Mad Hit Diamonds Extreme: normal cerrada; compra de bono y 13 continuaciones cerradas. Saldo conciliado en las 15 respuestas. Los enlaces abren el proveedor directamente.</p><table><thead><tr><th>Juego</th><th>Código nativo</th><th>Demo pública</th><th>Prueba</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>'
    page=page.replace('1 juego verificado · 178 pendientes',f'{len(verified)} juegos con prueba verificada · {179-len(verified)} pendientes')
    page=page.replace('<table>',f'<p>Lote: {html.escape(batch.get("state","sin iniciar"))}. <a href="../results/batch-pending.json">Ver pendientes</a></p><table>',1)
    (ROOT/'catalogs/demo-links.html').write_text(page,encoding='utf8')
    print(json.dumps({k:summary[k] for k in ('verified_games','verified_modes','new_gameplay_requests_sent')}))

if __name__=='__main__':main()
