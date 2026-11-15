"""Archive public WordPress metadata and bind links to the frozen official list."""
from collections import defaultdict
from datetime import datetime,timezone,date
import hashlib,html,json,re
from urllib.parse import urlsplit,urlencode,parse_qs
from har_probe import ROOT
from catalog_network import durable,fetch

SAFE_QUERY={'gamename','operator','server_url','currency','mode','lang','language','game','gameid','game_id'}

def public_launcher(value):
    if not value:return None
    # ACF values are JSON strings, not HTML text. Broad html.unescape would turn
    # a literal '&currency=' into the HTML entity '&curren' plus 'cy='.
    value=re.sub(r'&(?:amp|#0*38|#x0*26);','&',value,flags=re.I)
    u=urlsplit(value)
    if u.scheme!='https' or u.username or u.password:return None
    if u.hostname not in ('prrpeu3.com','demo.rubyplay.com'):return None
    q=parse_qs(u.query)
    if set(k.lower() for k in q)-SAFE_QUERY:return None
    if q.get('server_url'):
        endpoint=urlsplit(q['server_url'][0])
        if endpoint.scheme!='https' or endpoint.hostname!='srv.prrpeu3.com' or endpoint.query or endpoint.username:return None
    if any(re.search(r'(?i)(token|session|password|secret)=',x) for values in q.values() for x in values):return None
    return value

def main():
    folder=ROOT/'private/catalog-snapshots/rubyplay-api'
    original=json.loads((folder/'game-68986.body').read_bytes())
    collection=original['_links']['collection'][0]['href']
    if collection!='https://rubyplay.com/wp-json/wp/v2/games':raise ValueError('collection_owner_changed')
    official=json.loads((ROOT/'private/catalog-snapshots/rubyplay/complete-snapshot.json').read_text(encoding='utf8'))
    if not official['complete'] or not official['termination_verified']:raise ValueError('official_catalogue_not_complete')
    checkpoint=ROOT/'results/link-capture-checkpoint.json'
    state={'stage':'public_game_metadata_only','status':'running','gameplay_requests_sent':0,'captured_pages':[],
           'official_catalogue_entries':len(official['records']),'pid':__import__('os').getpid()}
    durable(checkpoint,state)
    records=[];pages=[];number=1;maxpages=None;total=None
    while True:
        url=collection+'?'+urlencode({'per_page':100,'page':number})
        meta,data=fetch('rubyplay-api',f'collection-page-{number}',url,follow_redirects=False)
        if meta.get('status')!=200:
            durable(checkpoint,{**state,'status':'stopped_http_non_success','http_status':meta.get('status')});return
        payload=json.loads(data)
        if not isinstance(payload,list):raise ValueError('collection_not_array')
        counts=meta['catalogue_pagination']
        if maxpages is None:maxpages=counts['pages'];total=counts['total']
        if counts!={'total':total,'pages':maxpages} or not 1<=maxpages<=30:raise ValueError('API_pagination_changed')
        pages.append({'page':number,'count':len(payload),'sha256':meta['sha256'],'captured_at':meta['finished_at'],
                     'private_response':f'private/catalog-snapshots/rubyplay-api/collection-page-{number}.body'})
        records.extend(payload);state['captured_pages']=pages;durable(checkpoint,state)
        if number==maxpages:break
        number+=1
    if len(records)!=total or len({r['id'] for r in records})!=total:raise ValueError('API_total_or_duplicates_mismatch')
    bylink={r['link']:r for r in records};byslug={r['slug']:r for r in records}
    upcoming=json.loads((ROOT/'catalogs/upcoming.json').read_text(encoding='utf8'))
    linked=[];nativegroups=defaultdict(list)
    for card in official['records']:
        match=bylink.get(card['source_url'])
        if not match and not card['detail_link_resolved']:
            # The upcoming section supplies its actual game link; title matching
            # remains same-source evidence and is not a cross-source native merge.
            candidates=[r for r in upcoming if card['title'] in r.get('announcement_text','')]
            if len(candidates)==1:match=bylink.get(candidates[0]['source_url'])
        row={**card,'native_identity':None,'status':'metadata_missing','gameplay_status':'not_started',
             'new_gameplay_requests_sent':0}
        if match:
            acf=match.get('acf',{});rawlink=acf.get('play_demo_url','');launch=public_launcher(rawlink)
            q=parse_qs(urlsplit(launch).query) if launch else {}
            native=q.get('gamename',[None])[0]
            if native and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',native):raise ValueError('invalid_native_id')
            row.update({'post_id':match['id'],'canonical_source_url':match['link'],
                'canonical_title':html.unescape(match['title']['rendered']),'native_identity':native,
                'declared_game_id':acf.get('game_id'),'declared_external_game_id':acf.get('external_game_id'),
                'release_date_declared':acf.get('release_date'),'public_demo_url':launch,
                'launcher_mode':q.get('mode',[None])[0],
                'status':'public_demo_link_declared_not_launched' if launch else 'no_usable_public_demo_link_declared',
                'evidence':{'api_post_id':match['id'],'api_page':next(p['page'] for p in pages if any(x['id']==match['id'] for x in json.loads((ROOT/p['private_response']).read_bytes())))}})
            if native:nativegroups[native].append(card['source_key'])
        linked.append(row)
    result={'provider':'rubyplay','scope':'Frozen official RubyPlay list; other catalogues deferred by user',
            'updated_at':datetime.now(timezone.utc).isoformat(),'official_entries':len(linked),
            'linked_metadata':sum('post_id' in r for r in linked),'public_demo_links':sum(bool(r.get('public_demo_url')) for r in linked),
            'native_identities':len(nativegroups),'metadata_collection_records_archived':total,'metadata_collection_pages':pages,
            'out_of_scope_API_posts_not_processed':total-sum('post_id' in r for r in linked),
            'native_alias_groups':[{ 'native_identity':k,'source_keys':v} for k,v in nativegroups.items() if len(v)>1],
            'games':linked,'new_gameplay_requests_sent':0}
    durable(ROOT/'catalogs/official-links.json',result)
    durable(checkpoint,{**state,'status':'completed','official_entries':len(linked),'public_demo_links':result['public_demo_links'],
        'metadata_missing':len(linked)-result['linked_metadata'],'native_identities':len(nativegroups)})
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,(list,dict))},ensure_ascii=False))

if __name__=='__main__':main()
