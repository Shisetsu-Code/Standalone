"""Pirots 5 official-demo campaign. Native progress only, no state overrides."""
import argparse,json,time,uuid
from decimal import Decimal as D
from pathlib import Path
from elk_client import Elk
from elk_protocol import parse_xml,mode_controls,purchase_tree,validate_result_closure,round_id,results,validate_fresh_demo
from endorphina_run import write_json

ROOT=Path(__file__).resolve().parent
WORLDS=('temple','ship','nest')

def progress(text):
    root=parse_xml(text);found={}
    for world in WORLDS:
        node=root.find("VAR[@id='collected-tokens-"+world+"']/STATE")
        if node is None:raise ValueError('native_progress_missing:'+world)
        value=int(node.text)
        if value<0 or value>7:raise ValueError('invalid_native_token_mask')
        found[world]=value
    return found

def verify_round(init,before,buy,check,control):
    def require(ok,error):
        if not ok:raise ValueError(error)
    require(control in mode_controls(init),'unpublished_control')
    require(buy.findtext('method')=='purchase' and check.findtext('method')=='checkwin','native_methods')
    require(all(r.findtext('errorcode')=='0' and r.findtext('player/currency')=='EUR' for r in (init,before,buy,check)),'native_demo_acceptance')
    info=buy.find('roundinfo');require(info is not None,'native_round_missing')
    rid=buy.findtext('roundid');require(bool(rid) and rid!='0' and rid==info.findtext('roundid')==check.findtext('roundid') and rid!=before.findtext('roundid'),'native_round_correlation')
    cost=D(info.findtext('betamount'));win=D(info.findtext('winamount'));balance=D(before.findtext('player/balance'));after=D(check.findtext('player/balance'))
    require(info.findtext('bmode')==control['mode'] and info.findtext('betlevel')==control['betlevel'] and info.findtext('currency')=='EUR','native_control')
    require(cost==D(control['amount']) and win>=0 and balance>=cost and balance-cost+win==after==D(info.findtext('balanceafterwin')),'incremental_wallet')
    require(D(before.findtext('gamesession/totbet'))+cost==D(check.findtext('gamesession/totbet')) and D(before.findtext('gamesession/totwon'))+win==D(check.findtext('gamesession/totwon')),'cumulative_session_totals')
    if check.find('gamesession/netposition') is not None:require(D(check.findtext('gamesession/netposition'))==D(check.findtext('gamesession/totwon'))-D(check.findtext('gamesession/totbet')),'cumulative_net_position')
    native=purchase_tree(buy)
    require(native.get('bmode')==control['mode'] and native.get('betlevel')==control['betlevel'] and native.get('variant')==control.get('variant'),'native_purchase_identity')
    require(D(native.get('betamount'))==cost and D(native.get('winamount'))==win and native.get('currency','EUR')=='EUR','native_purchase_money')
    validate_result_closure(init,buy,control)
    nodes=native.findall('RESULT');indices=[n.get('resultIndex') for n in nodes]
    if any(v is not None for v in indices):require(all(v is not None for v in indices) and [int(v) for v in indices]==list(range(len(nodes))),'native_result_indices')
    return {'cost':str(cost),'win':str(win),'balance_before':str(balance),'balance_after':str(after),'wallet_check':'match','closed':True,'round_id':round_id(rid),'native_results':len(nodes)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-per-world',type=int,default=600);parser.add_argument('--progress-mode',choices=['DEF','X01','X02','X03','X04','X05'],default='DEF');parser.add_argument('--resume');args=parser.parse_args()
    if not 1<=args.max_per_world<=1000:raise ValueError('bounded_campaign_required')
    game=next(g for g in json.loads((ROOT/'elk/catalog.json').read_text(encoding='utf8')) if g['id']=='10266')
    if args.resume:
        import re
        if not re.fullmatch('[a-f0-9]{32}',args.resume):raise ValueError('campaign_path')
    folder=ROOT/'elk/boss-campaigns'/(args.resume or uuid.uuid4().hex)
    if not args.resume:folder.mkdir(parents=True);(folder/'rounds').mkdir()
    private=ROOT.parent/'elk-private'/('campaign-'+folder.name+'.json')
    status=json.loads((folder/'status.json').read_text(encoding='utf8')) if args.resume else {'campaign':folder.name,'game':game,'status':'initializing','progress':{},'rounds':[],'boss_cases':[],'created':time.time()}
    current={'path':folder/'initialization.json','start':0,'document':{'game':game}}
    def save(client):
        current['document'].update(launch=getattr(client,'launch',{}),trace=client.trace[current['start']:])
        write_json(current['path'],current['document']);write_json(folder/'status.json',status)
        write_json(private,{'campaign':folder.name,'gameid':'10266','session_key':client.key,'launch':getattr(client,'launch',{}),'uncertain':current['document'].get('status')=='sending'})
    client=Elk(game,save)
    try:
        if args.resume:
            checkpoint=json.loads(private.read_text(encoding='utf8'))
            if checkpoint['campaign']!=folder.name or checkpoint['gameid']!='10266' or checkpoint['uncertain'] or not checkpoint['session_key']:raise ValueError('unsafe_or_uncertain_resume')
            saved=json.loads((folder/'initialization.json').read_text(encoding='utf8'));init=parse_xml(saved['trace'][0]['response']);client.launch=saved['launch'];client.key=checkpoint['session_key'];client.uses_bmode=True;client.min_spin_delay_ms=int(init.findtext('gamesession/minspindelay'));client.last_purchase_finished=time.monotonic()
            client.session.headers.update({'X-CLIENT-VERSION':client.launch['client_revision'],'X-ECF-VERSION':client.launch['ecf_revision']})
            before=init;state=progress(init.findtext('variants/pubstate/init'))
            if status['rounds']:
                last=json.loads((folder/'rounds'/('%05d.json'%len(status['rounds']))).read_text(encoding='utf8'));before=parse_xml(last['trace'][-1]['response']);state=progress(parse_xml(last['trace'][0]['response']).findtext('game/pubstate/roundend'))
        else:
            init=client.open();state=progress(init.findtext('variants/pubstate/init'));before=init
        validate_fresh_demo(init);controls=mode_controls(init);seen={r['round_id'] for r in status['rounds']};status.update(status='progressing',progress=state);status.pop('error',None)
        def play(control,kind):
            nonlocal before,state
            if D(before.findtext('player/balance'))<D(control['amount']):raise ValueError('demo_balance_insufficient')
            number=len(status['rounds'])+1
            doc={'game':game,'control':control,'kind':kind,'sequence':number,'progress_before':dict(state),'status':'sending'}
            current.update(path=folder/'rounds'/('%05d.json'%number),start=len(client.trace),document=doc)
            save(client)
            buy=client.purchase(control);check=client.check(buy);financial=verify_round(init,before,buy,check,control)
            if financial['round_id'] in seen:raise ValueError('duplicate_paid_round')
            seen.add(financial['round_id']);state=progress(buy.findtext('game/pubstate/roundend'))
            doc.update(summary=financial,progress_after=dict(state),results=results(parse_xml(client.trace[current['start']]['response'])),status='completed')
            status['rounds'].append({'sequence':number,'kind':kind,'control':control,**financial});status.update(progress=state)
            if kind=='boss':status['boss_cases'].append({'mode':control['mode'],'sequence':number})
            before=check;save(client)
            tokens=sum(v.bit_count() for v in state.values())
            if number%10==0 or doc['progress_before']!=state or kind=='boss':print(json.dumps({'campaign':folder.name,'round':number,'kind':kind,'world':control.get('variant'),'mode':control['mode'],'tokens':tokens,'masks':state,'boss_completed':len(status['boss_cases'])}),flush=True)
        boss=[c for c in controls if c.get('variant')=='boss']
        for target in boss:
            if any(c['mode']==target['mode'] for c in status['boss_cases']):continue
            attempts={world:0 for world in WORLDS}
            while any(state[world]!=7 for world in WORLDS):
                world=next(world for world in WORLDS if state[world]!=7)
                if attempts[world]>=args.max_per_world:raise ValueError('native_progress_limit:'+world)
                attempts[world]+=1
                play(next(c for c in controls if c.get('variant')==world and c['mode']==args.progress_mode),'progression')
            play(target,'boss')
        status['status']='completed';write_json(folder/'status.json',status)
    except Exception as error:
        status.update(status='needs_review',error=type(error).__name__+':'+str(error)[:300]);write_json(folder/'status.json',status)
        print(json.dumps({'campaign':folder.name,'status':status['status'],'error':status['error'],'progress':status['progress'],'boss_completed':len(status['boss_cases'])}),flush=True)
    finally:client.session.close()
    print(json.dumps({'campaign':folder.name,'status':status['status'],'rounds':len(status['rounds']),'boss_completed':len(status['boss_cases'])}),flush=True)

if __name__=='__main__':main()
