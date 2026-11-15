"""Official anonymous demo QA. Native HTTP, no HAR sessions or browser automation."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import uuid
import requests
from analyze_hars import ROOT,clean,save
from protocol import minimum_modes,audit_round,settlement_rejected,take_round_request

API='https://demo.spinart.cloud'
STATE={}

def atomic(relative,value):
    path=ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,path)

def checkpoint(status,**fields):
    STATE.update(status=status,updated_at=time.time(),pid=os.getpid(),**fields)
    atomic('private/checkpoint.json',STATE)

class Client:
    def __init__(self,game):
        self.game=game;self.folder=ROOT/'private/sessions'/(game['game_id']+'-'+uuid.uuid4().hex)
        self.session=requests.Session();self.session.trust_env=False
        self.session.headers.update({'Origin':'https://cdn-demo.spinart.cloud','Referer':'https://cdn-demo.spinart.cloud/',
                                     'User-Agent':'PeterAndSons-Demo-QA/1.0'})
        self.key=str(secrets.randbelow(int(time.time()*1000)))
        atomic((self.folder/'credentials.json').relative_to(ROOT),{'wallet':game['wallet'],'game':game['game_id'],'key':self.key,'source':'new_anonymous_launch_never_HAR'})

    def call(self,path,body,name):
        if path not in ['/cfg','/authenticate','/game/recover','/game/info','/campaigns','/game/play','/game/complete']:raise ValueError('operation_not_reviewed')
        if (ROOT/'private/remote-block.json').exists():raise ValueError('provider_block_retained')
        target=self.folder/(name+'.json')
        if target.exists():raise ValueError('existing_request_never_replayed')
        record={'status':'sending','path':path,'request':clean(body),'started_at':time.time()}
        atomic(target.relative_to(ROOT),record)
        try:
            response=self.session.post(API+path,json=body,timeout=(15,45),allow_redirects=False)
            record.update(http_status=response.status_code,status='received')
            try:document=response.json();record['response']=clean(document)
            except ValueError:
                record['response']={'body_sha256':hashlib.sha256(response.content).hexdigest(),'bytes':len(response.content)}
                document=None
            atomic(target.relative_to(ROOT),record)
            if response.status_code in (403,429,503):
                atomic('private/remote-block.json',{'http_status':response.status_code,'operation':path,'game':self.game['game_id'],
                                                  'observed_at':time.time(),'intent':target.relative_to(ROOT).as_posix()})
                raise ValueError('provider_block_'+str(response.status_code))
            if response.status_code!=200 or not isinstance(document,dict):raise ValueError('native_http_or_body_error_'+str(response.status_code))
            return document
        except Exception as error:
            record['error']=str(error)[:300];atomic(target.relative_to(ROOT),record);raise

    def initialize(self):
        game=self.game['game_id'];wallet=self.game['wallet']
        cfg=self.call('/cfg',{'server':API,'wallet':wallet,'operator':'demo','gameCode':game,'key':self.key,'language':'en'},'configuration')
        if cfg.get('adapter')!='standard' or cfg.get('loadGame') is not True:raise ValueError('unsupported_native_adapter')
        auth=self.call('/authenticate',{'wallet':wallet,'operator':'demo','key':self.key,'provider':'peterandsons','game':game},'authentication')
        if not auth.get('token') or auth.get('currencyDecimals')!=2:raise ValueError('authentication_or_currency_unreviewed')
        self.session.headers['Authorization']='Bearer '+auth['token']
        atomic((self.folder/'credentials.json').relative_to(ROOT),{'wallet':wallet,'game':game,'key':self.key,'token':auth['token'],'source':'new_anonymous_launch_never_HAR'})
        common={'game':game,'provider':'peterandsons'}
        recover=self.call('/game/recover',dict(common,complete=False),'recovery')
        if recover.get('rounds')!=[]:raise ValueError('fresh_demo_has_pending_round')
        info=self.call('/game/info',common,'information')
        modes=minimum_modes(info)
        atomic('private/plans/'+game+'.json',{'game':game,'modes':modes,'frozen_before_paid_action':True,
                                            'info':clean(info),'auth':clean(auth),'session':self.folder.name})
        return auth['balance'],info,modes

def publish(catalogue):
    games=[]
    for game in catalogue:
        gid=game['game_id'];plan=ROOT/'private/plans'/(gid+'.json');modes=[]
        if plan.exists():
            for profile in json.loads(plan.read_text(encoding='utf8'))['modes']:
                path=ROOT/'private/rounds'/(gid+'--'+profile['id']+'.json')
                row=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
                mode=dict(profile,status='pending')
                if row.get('status')=='verified':
                    mode.update(status='verified_remote',cost=row['audit']['cost'],payout=row['audit']['payout'],
                                internal_steps=row['audit']['internal_steps'],checks={k:True for k in ['demo','action_binding','cost','result','round_closed','balance']},
                                evidence=[{'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}])
                elif row:mode['status']='needs_review'
                modes.append(mode)
        for offer_file in (ROOT/'private/conditional-offers').glob(gid+'--*.json'):
            offer=json.loads(offer_file.read_text(encoding='utf8'))
            for action in offer['actions']:
                modes.append({'id':offer['parent_mode']+'::offer::'+action,'kind':'purchase','status':'pending'})
        status='complete' if modes and all(m['status']=='verified_remote' for m in modes) else ('needs_review' if any(m['status']=='needs_review' for m in modes) else 'pending')
        if status=='pending' and any(m['status']=='verified_remote' for m in modes):status='partial'
        if (ROOT/'private/holds'/(gid+'.json')).exists():status='needs_review'
        games.append({'id':gid,'title':game['title'],'classification':game['classification'],'status':status,'modes':modes})
    atomic('results/provider-report.json',{'schema_version':1,'provider':'peterandsons','provider_name':'Peter & Sons',
                                         'catalogue_total':len(catalogue),'catalogue_frozen':True,'games':games,
                                         'notes':'Official anonymous demos. Native amounts; one full round per identified mode at its native minimum. Internal bonus steps remain separate. No exhaustive line or stake permutations, unobserved random choices, or HAR session replay. Central integration pending.'})

def run():
    catalogue=json.loads((ROOT/'results/catalogue.json').read_text(encoding='utf8'))
    held=[]
    for game in catalogue:
        if not game['valid_public_demo_link'] or game['classification']!='slot':raise ValueError('catalogue_entry_requires_review:'+game['id'])
        gid=game['game_id']
        if (ROOT/'private/holds'/(gid+'.json')).exists():
            held.append(gid);checkpoint('game_held_without_replay',game=gid);continue
        existing=list((ROOT/'private/rounds').glob(gid+'--*.json'))
        if any(json.loads(p.read_text(encoding='utf8')).get('status')!='verified' for p in existing):raise ValueError('prior_operation_needs_review:'+gid)
        plan=ROOT/'private/plans'/(gid+'.json')
        if plan.exists() and all((ROOT/'private/rounds'/(gid+'--'+m['id']+'.json')).exists() for m in json.loads(plan.read_text())['modes']):continue
        if (ROOT/'private/remote-block.json').exists():raise ValueError('provider_block_retained')
        while True:
            cadence=ROOT/'private/cadence.json';last=json.loads(cadence.read_text()).get('last_started_at',0) if cadence.exists() else 0
            wait=40-(time.time()-last)
            if wait<=0:break
            checkpoint('waiting_interval',game=gid,remaining_seconds=round(wait,1));time.sleep(min(wait,5))
        atomic('private/cadence.json',{'last_started_at':time.time(),'game':gid,'minimum_interval_seconds':40})
        checkpoint('initializing_demo',game=gid,mode=None)
        client=Client(game)
        try:
            balance,info,modes=client.initialize()
            for profile in modes:
                target=ROOT/'private/rounds'/(gid+'--'+profile['id']+'.json')
                if target.exists():continue
                checkpoint('verifying_mode',game=gid,mode=profile['id'])
                record={'status':'started','game':gid,'mode':profile,'balance_before':balance,'session':client.folder.name}
                atomic(target.relative_to(ROOT),record)
                try:
                    play_body={'game':gid,'provider':'peterandsons','action':profile['id'],'complete':False,'asyncWin':False,'bet':profile['bet']}
                    play=client.call('/game/play',play_body,profile['id']+'-play')
                    record.update(play_request=play_body,play_response=clean(play));atomic(target.relative_to(ROOT),record)
                    if 'take_round' in play.get('wager',{}).get('next',[]):
                        options=[action for action in play['wager']['next'] if action!='take_round']
                        if options:
                            state=play['wager']['data'][-1]['state']
                            atomic('private/conditional-offers/'+gid+'--'+profile['id']+'.json',{'game':gid,'parent_mode':profile['id'],
                                'actions':options,'state':state,'native_configuration':info.get('config',{}).get('per_state',{}).get(state,{}).get('continuation_offers'),
                                'status':'observed_not_executed','note':'Distinct conditional purchases; parent round is collected using advertised Take, never counted as testing these options.'})
                        take_body=take_round_request(gid,play)
                        continued=client.call('/game/play',take_body,profile['id']+'-take-round')
                        record['continuations']=[{'request':take_body,'response':clean(continued),'source_binding':'Official Slotify connector, same roundId, optional bet omitted.'}]
                        atomic(target.relative_to(ROOT),record);play=continued
                    if play.get('wager',{}).get('next') or not play.get('wager',{}).get('data') or play['wager']['data'][-1].get('closes_game_round') is not True:raise ValueError('unreviewed_pending_round_or_choice')
                    complete_body={'game':gid,'provider':'peterandsons','roundId':play['roundId'],'asyncWin':False}
                    complete=client.call('/game/complete',complete_body,profile['id']+'-complete')
                    record.update(complete_request=complete_body,complete_response=clean(complete));atomic(target.relative_to(ROOT),record)
                    audit=audit_round(balance,info,play_body,record['play_response'],complete_body,complete,continuations=record.get('continuations'))
                    record.update(status='verified',audit=audit);atomic(target.relative_to(ROOT),record)
                    balance=complete['balance'];publish(catalogue)
                    print(json.dumps({'game':gid,'mode':profile['id'],'status':'verified','internal_steps':audit['internal_steps']}),flush=True)
                except Exception as error:
                    record.update(status='needs_review',error=str(error)[:300]);atomic(target.relative_to(ROOT),record)
                    completion=client.folder/(profile['id']+'-complete.json')
                    effective=record.get('continuations',[{'response':record.get('play_response',{})}])[-1]['response']
                    if completion.exists() and settlement_rejected(effective,json.loads(completion.read_text(encoding='utf8'))):
                        atomic('private/holds/'+gid+'.json',{'game':gid,'mode':profile['id'],'reason':'native_settlement_rejected',
                            'provider_http_status':400,'provider_error_code':'TRANSACTION_REJECTED','settlement_not_verified':True,
                            'never_repeat_paid_entry':True,'evidence':completion.relative_to(ROOT).as_posix(),
                            'sha256':hashlib.sha256(completion.read_bytes()).hexdigest(),'recorded_at':time.time()})
                        held.append(gid);publish(catalogue)
                        print(json.dumps({'event':'game_held','game':gid,'mode':profile['id'],'reason':'native_settlement_rejected','remaining_games_continue':True}),flush=True)
                        break
                    publish(catalogue);raise
            checkpoint('game_held_without_replay' if gid in held else 'game_complete',game=gid)
        finally:client.session.close()
    conditional=any((ROOT/'private/conditional-offers').glob('*.json'))
    publish(catalogue);checkpoint('campaign_finished_with_holds' if held else ('campaign_finished_with_pending_offers' if conditional else 'campaign_complete'),game=None,mode=None,held_games=held)

def main():
    lock=ROOT/'private/campaign.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,json.dumps({'pid':os.getpid(),'started_at':time.time()}).encode());os.close(fd)
    try:run()
    except BaseException as error:
        checkpoint('stopped_for_review',error_type=type(error).__name__,error=str(error)[:300]);print(json.dumps(STATE),flush=True)
    finally:lock.unlink()

if __name__=='__main__':main()
