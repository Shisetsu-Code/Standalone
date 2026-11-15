"""Offline, allowlisted NetEnt/Evolution HAR evidence. No network or session replay."""
import base64
from collections import Counter
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT=Path(__file__).resolve().parent
DESKTOP=Path('C:/Users/Shisetsu/Desktop')
FILES=['games.evolution.com_Archive [26-10-29 '+stamp+'].har' for stamp in ['08-24-46','08-26-44','08-31-55']]


def decoded(entry):
    content=entry['response'].get('content',{})
    value=content.get('text','')
    return base64.b64decode(value).decode('utf8') if content.get('encoding')=='base64' else value


def save(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def internal_steps(value,path='game'):
    result=[]
    if isinstance(value,dict):
        if path!='game' and 'spinMode' in value:
            result.append({'path':path,'mode':value['spinMode'],
                           'win_reference':value.get('win',{}).get('total'),
                           'settlement':'included_in_parent; not_an_additional_wager_or_wallet_credit'})
        for key,item in value.items():
            result.extend(internal_steps(item,path+'.'+key))
    elif isinstance(value,list):
        for index,item in enumerate(value):
            result.extend(internal_steps(item,path+'['+str(index)+']'))
    return result


def reconcile(request,response,previous):
    body=response['result'];cash=body['user']['balance']['cash'];game=body['game']
    opening,after_bet,closing=(Decimal(cash[key]) for key in ['atStart','afterBet','atEnd'])
    stake=Decimal(str(request['stake']));credit=Decimal(game['win']['total'])
    checks={'success':response['success'] is True,'demo':request['playMode']=='demo',
            'continuity':previous is not None and Decimal(previous)==opening,
            'request_stake_matches_game':stake==Decimal(game['stake']),
            'debit':opening-stake==after_bet,'credit':after_bet+credit==closing,
            'wallet_ledger':opening-stake+credit==closing,'nonnegative_credit':credit>=0,
            'closed_state':game.get('hasState') is False,
            'ordinary_entry':request.get('gameMode')==0 and request.get('bonusId') is None}
    return {'opening_balance':str(opening),'after_bet':str(after_bet),'closing_balance':str(closing),
            'debit':str(stake),'credit':str(credit),'entry_kind':'normal',
            'checks':checks,'passed':all(checks.values()),'internal_steps':internal_steps(game)}


def analyze():
    sources=[];catalog={};pages=[];rounds=[];ws=[];captures=[]
    for capture,name in enumerate(FILES,1):
        raw=(DESKTOP/name).read_bytes();entries=json.loads(raw)['log']['entries']
        sources.append({'source_id':'H'+str(capture),'file':name,'sha256':hashlib.sha256(raw).hexdigest(),
                        'bytes':len(raw),'entries':len(entries),'index_base':0})
        previous=None;game_currency=None;starts=[];settings=[]
        for index,entry in enumerate(entries):
            u=urlsplit(entry['request']['url']);reference=f'H{capture}:entries[{index}]'
            if u.hostname=='games.evolution.com' and u.path=='/wp-json/wp/v2/pages':
                rows=json.loads(decoded(entry));headers={h['name'].lower():h['value'] for h in entry['response']['headers']}
                pages.append({'reference':reference,'page':int(parse_qs(u.query)['page'][0]),'rows':len(rows),
                              'declared_total':int(headers['x-wp-total']),'declared_pages':int(headers['x-wp-totalpages'])})
                for row in rows:
                    terms=[term for group in row.get('_embedded',{}).get('wp:term',[]) for term in group]
                    types=[term['name'] for term in terms if term.get('taxonomy')=='game_type']
                    features=[term['name'] for term in terms if term.get('taxonomy')=='game_feature']
                    catalog[row['id']]={'page_id':row['id'],'slug':row['slug'],'title':html.unescape(row['title']['rendered']),
                                        'provider':row['game_provider']['post_title'],'site_url':row['link'],
                                        'game_types':types,'in_slot_scope':types==['Slots'],
                                        'public_demo_advertised':row['acf']['embed_type']=='game',
                                        'embed_type':row['acf']['embed_type'],'table_id':row['acf']['game_id'],
                                        'features_advertised':features,'catalog_reference':reference,
                                        'runtime_status':'not_tested_in_fresh_demo'}
            if u.hostname=='games.evolution.com' and u.path=='/wp-json/games/v1/start':
                starts.append({'reference':reference,'page_id':int(parse_qs(u.query)['id'][0]),
                               'launch_captured':True,'captured_auth_reused':False})
            if entry['response']['status']==101:
                ws.append({'reference':reference,'host':u.hostname,'path':u.path,
                           'messages_captured':len(entry.get('_webSocketMessages',[])),
                           'financial_outcomes_available':False})
            if (u.hostname or '').endswith('.redtiger.cash') and u.path.endswith('/platform/game/settings'):
                body=json.loads(decoded(entry))['result'];game=body['game'];user=body['user']
                previous=user['balance']['cash'];game_currency=user['currency']['code']
                settings.append({'reference':reference,'platform':'redtiger_http','currency':game_currency,
                                 'balance':previous,'has_feature_buy':game['hasFeatureBuy'],
                                 'feature_buy_count':len(game['featureBuy']),'has_gamble':game['hasGambleGame'],
                                 'has_choices':game['hasChoices'],'game_modes':game['gameModes']})
            if (u.hostname or '').endswith('.redtiger.cash') and u.path.endswith('/platform/game/spin'):
                request=json.loads(entry['request']['postData']['text']);response=json.loads(decoded(entry))
                result=reconcile(request,response,previous)
                result.update(reference=reference,runtime_game_id=request['gameId'],currency=game_currency,
                              mode=request['playMode'],source='captured_HAR_only_not_a_fresh_test')
                rounds.append(result);previous=result['closing_balance']
        captures.append({'source_id':'H'+str(capture),'starts':starts,'settings_observed':settings})
    ordered=list(catalog.values());save('sources.json',{'sources':sources,'original_files_modified':False})
    save('catalog-har.json',{'games':ordered,'pages':pages,'catalog_complete':False})
    save('capture-rounds.json',rounds);save('websocket-evidence.json',ws);save('capture-inventory.json',captures)
    summary={'provider':'NetEnt','catalog_provider_id':647,'catalog_titles_declared':max(p['declared_total'] for p in pages),
             'catalog_titles_captured':len(ordered),'slot_titles_captured':sum(g['in_slot_scope'] for g in ordered),
             'advertised_game_embeds':sum(g['public_demo_advertised'] for g in ordered),
             'captured_pages':sorted({p['page'] for p in pages}),'declared_pages':max(p['declared_pages'] for p in pages),
             'har_rounds_verified':sum(r['passed'] for r in rounds),'har_rounds_failed':sum(not r['passed'] for r in rounds),
             'har_checks_passed':sum(sum(r['checks'].values()) for r in rounds),
             'har_checks_failed':sum(sum(not v for v in r['checks'].values()) for r in rounds),
             'har_internal_steps':sum(len(r['internal_steps']) for r in rounds),
             'internal_modes':dict(Counter(s['mode'] for r in rounds for s in r['internal_steps'])),
             'websocket_connections':len(ws),'websocket_messages_captured':sum(r['messages_captured'] for r in ws),
             'fresh_demo_games_verified':0,'fresh_gameplay_requests_sent':0,
             'coverage':'Four captured ordinary entries in DontEatTheCandy; nested bonus steps stay under their parent. NetEnt Horizon outcomes are missing from these HARs. No live/session replay.'}
    save('summary.json',summary);return summary


if __name__=='__main__':print(json.dumps(analyze(),ensure_ascii=False))
