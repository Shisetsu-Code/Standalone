"""Archive the site's published, read-only Bricks pagination with fresh page data."""
import hashlib,json,re
from datetime import datetime,timezone
from urllib.parse import urlsplit
from catalog_dom import DOM
from catalog_network import fetch,durable
from build_catalog import source_cards
from har_probe import ROOT

def main():
    source='rubyplay';key='page-1-verified-chain'
    folder=ROOT/'private/catalog-snapshots'/source
    meta=json.loads((folder/(key+'.meta.json')).read_text(encoding='utf8'))
    if meta.get('status')!=200:raise ValueError('initial_page_not_successful')
    raw=(folder/(key+'.body')).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('initial_page_pin_mismatch')
    text=raw.decode('utf8');tree=DOM(text).root
    trail=next(n for n in tree.walk() if n.attrs.get('data-query-element-id')=='sqkeya')
    maxpages=int(trail.attrs['data-max-pages'])
    if not 1<=maxpages<=100:raise ValueError('unexpected_page_limit')
    config=json.loads(re.search(r'var bricksData\s*=\s*(\{.*?\});',text,re.S).group(1))
    endpoint=config['restApiUrl']+'load_query_page?lang=en'
    if urlsplit(endpoint).hostname!='rubyplay.com':raise ValueError('catalogue_endpoint_owner_changed')
    body=next(n for n in tree.walk() if n.tag=='body')
    postid=re.search(r'\bpage-id-(\d+)\b',body.attrs['class']).group(1)
    query=trail.attrs['data-query-vars']
    q=json.loads(query)
    if q.get('post_type')!='games':raise ValueError('not_a_game_catalogue_query')
    pages=[{'page':1,'cards':source_cards(text,source),'response_sha256':meta['sha256'],
            'private_response':(folder/(key+'.body')).relative_to(ROOT).as_posix(),'captured_at':meta['finished_at'],
            'range':[int(trail.attrs['data-start']),int(trail.attrs['data-end'])]}]
    total=None
    for number in range(2,maxpages+1):
        payload={'postId':postid,'queryElementId':trail.attrs['data-query-element-id'],'previewTemplateId':'0',
          'componentId':False,'queryVars':query,'page':number,'nonce':config['nonce'],'lang':'en',
          'mainQueryId':False,'activeSearchTemplate':'0','urlParams':{}}
        # All values are from the freshly downloaded page or the observed public
        # catalogue schema; no captured authentication or game session is copied.
        request=json.dumps(payload).encode('utf8')
        durable(folder/(f'page-{number}-verified-chain.request.private.json'),payload)
        response,data=fetch(source,f'page-{number}-verified-chain',endpoint,data=request,
            headers={'Content-Type':'application/json; charset=UTF-8','Referer':'https://rubyplay.com/reel-winners/','Origin':'https://rubyplay.com'})
        if response.get('status')!=200:raise RuntimeError('catalogue_page_non_success_stop')
        parsed=json.loads(data);updated=parsed['updated_query']
        if updated.get('query_vars',{}).get('paged')!=number or updated['max_num_pages']!=maxpages:
            raise ValueError('pagination_identity_or_end_changed')
        if total is not None and total!=updated['count']:raise ValueError('catalogue_count_changed_mid_capture')
        total=updated['count'];cards=source_cards(parsed['html'],source)
        if len(cards)!=updated['end']-updated['start']+1:raise ValueError('card_range_mismatch')
        if updated['start']!=pages[-1]['range'][1]+1:raise ValueError('pagination_gap')
        pages.append({'page':number,'cards':cards,'response_sha256':response['sha256'],
            'private_response':(folder/(f'page-{number}-verified-chain.body')).relative_to(ROOT).as_posix(),
            'captured_at':response['finished_at'],'range':[updated['start'],updated['end']]})
        print(json.dumps({'page':number,'cards':len(cards),'range':pages[-1]['range']}),flush=True)
    records=[r for p in pages for r in p['cards']]
    if len(records)!=total or pages[-1]['range'][1]!=total or len({r['source_key'] for r in records})!=len(records):
        raise ValueError('catalogue_total_or_duplicate_mismatch')
    # Termination follows the site's declared max_num_pages/count plus the
    # contiguous final response end==count, not an invented page past the end.
    snapshot={'source':source,'source_url':'https://rubyplay.com/reel-winners/','complete':True,
        'captured_at':datetime.now(timezone.utc).isoformat(),'declared_total':total,'declared_pages':maxpages,
        'termination_verified':True,'termination_evidence':'All declared pages contiguous; final updated_query.end equals count and page equals max_num_pages.',
        'tls_validation':'CERT_REQUIRED + hostname; existing Mozilla roots and official alternate intermediate; no root added',
        'pages':pages,'records':records}
    durable(ROOT/'private/catalog-snapshots/rubyplay/complete-snapshot.json',snapshot)
    print(json.dumps({'source':source,'complete':True,'records':len(records),'pages':len(pages)}))

if __name__=='__main__':main()
