"""Freeze captured catalogue provenance and gate gameplay on complete sources."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib,json,re,unicodedata
from pathlib import Path
from urllib.parse import urlsplit,urljoin,parse_qs,urlencode
from catalog_dom import DOM
from catalog_network import durable
from har_probe import ROOT,FILES

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s).casefold() if c.isalnum())

def source_cards(text,source):
    tree=DOM(text).root
    if source=='rubyplay':
        anchors=[n for n in tree.walk() if n.tag=='a' and n.parent.tag=='h3' and
                 (re.fullmatch(r'/games/[^/]+/',urlsplit(n.attrs.get('href','')).path) or n.parent.has('brxe-gvgnos'))]
    else:
        grids=[n for n in tree.walk() if n.attrs.get('id')=='top_games_filter']
        if not grids:return []
        anchors=[n for n in grids[0].walk() if n.tag=='a' and n.has('slotPageOverlay-link')]
    rows=[]
    for a in anchors:
        path=urlsplit(a.attrs.get('href','')).path
        detail_link=bool(re.fullmatch(r'/games/[^/]+/',path)) if source=='rubyplay' else True
        key=path.rstrip('/').split('/')[-1] if detail_link else 'listing-title:'+hashlib.sha256(a.text().encode()).hexdigest()[:16]
        rows.append({'source':source,'source_key':key,'detail_link_resolved':detail_link,
                     'title':a.text(),'source_url':urljoin('https://rubyplay.com' if source=='rubyplay' else 'https://slotcatalog.com',path)})
    return rows

def main():
    now=datetime.now(timezone.utc).isoformat()
    folder=ROOT/'private'/'har-documents'
    pages=[];records={}
    index=json.loads((ROOT/'har-index.json').read_text(encoding='utf8'))
    capture_meta={Path(d['private_file']).name:d for h in index for d in h['documents']}
    def keep_rows(rows,proof):
        for row in rows:
            source=row['source'];key=(source,row['source_key'])
            record=records.setdefault(key,{**row,'native_identity':None,'identity_status':'unresolved_source_record',
                'aliases':[],'provenance':[],'demo_status':'not_checked_live','qa_status':'not_started_catalogue_gate'})
            if proof not in record['provenance']:record['provenance'].append(proof)
            if row['title'] and row['title']!=record['title'] and row['title'] not in record['aliases']:record['aliases'].append(row['title'])
    def append_page(source,number,name,profile):
        raw=(folder/name).read_bytes();data=json.loads(raw) if name.endswith('.json') else None
        html=data['html'] if data else raw.decode('utf8')
        rows=source_cards(html,source)
        entry={'source':source,'page':number,'view':profile,'capture_document':name,
               'captured_at':capture_meta[name].get('captured_at'),
               'captured_body_sha256':hashlib.sha256(raw).hexdigest(),'cards':rows,'card_count':len(rows)}
        if data:
            q=data['updated_query'];entry['declared_total']=q['count'];entry['declared_pages']=q['max_num_pages']
            entry['range']=[q['start'],q['end']]
            if q.get('query_vars',{}).get('paged')!=number:raise ValueError('page_identity_mismatch')
        else:
            dom=DOM(html).root
            if source=='rubyplay':
                trail=next(n for n in dom.walk() if n.attrs.get('data-query-element-id')=='sqkeya')
                entry['declared_pages']=int(trail.attrs['data-max-pages']);entry['range']=[int(trail.attrs['data-start']),int(trail.attrs['data-end'])]
            else:
                nums=[int(m.group(1) or 1) for n in dom.walk() if n.tag=='a'
                      and (m:=re.fullmatch(r'/es/soft/Ruby-Play(?:/(\d+))?',urlsplit(n.attrs.get('href','')).path))]
                entry['declared_pages']=max(nums)
                entry['next_page_present']=any(n.tag=='a' and n.text().casefold()=='siguiente' for n in dom.walk())
        pages.append(entry)
        proof={'page':number,'view':profile,'document_sha256':entry['captured_body_sha256']}
        keep_rows(rows,proof)
    complete_path=ROOT/'private/catalog-snapshots/rubyplay/complete-snapshot.json'
    official=json.loads(complete_path.read_text(encoding='utf8')) if complete_path.exists() else None
    if official:
        if not official['complete'] or not official['termination_verified']:raise ValueError('official_snapshot_incomplete')
        for p in official['pages']:
            archived=ROOT/p['private_response']
            if not archived.resolve().is_relative_to(ROOT) or hashlib.sha256(archived.read_bytes()).hexdigest()!=p['response_sha256']:
                raise ValueError('official_archive_hash_mismatch')
            entry={'source':'rubyplay','page':p['page'],'view':'official_live_complete','captured_at':p['captured_at'],
                'archive_response':p['private_response'],'captured_body_sha256':p['response_sha256'],
                'cards':p['cards'],'card_count':len(p['cards']),'declared_total':official['declared_total'],
                'declared_pages':official['declared_pages'],'range':p['range']}
            pages.append(entry);keep_rows(p['cards'],{'page':p['page'],'view':entry['view'],'document_sha256':p['response_sha256']})
    else:
        for n,name in ((1,'0-325.html'),(2,'0-502.json'),(3,'0-553.json'),(4,'0-586.json')):
            append_page('rubyplay',n,name,'official_reel_winners')
    for n,name,profile in ((1,'2-133.html','captured_initial_GET'),(1,'2-217.html','SYEAR_AR'),
                           (2,'2-341.html','captured_initial_GET'),(2,'2-401.html','SYEAR_AR')):
        append_page('slotcatalog',n,name,profile)

    # Upcoming entries are retained separately from the published catalogue.
    upcoming=[]
    for n in DOM((folder/'0-165.html').read_text(encoding='utf8')).root.walk():
        if n.tag=='a' and n.has('upcoming-overlay'):
            upcoming.append({'source':'rubyplay','source_url':n.attrs.get('href'),
                             'announcement_text':n.text(),'status':'upcoming_not_in_published_denominator'})

    launches=[]
    for source_number,path in enumerate(FILES):
        har=json.loads(path.read_text(encoding='utf-8-sig'))
        for i,e in enumerate(har['log']['entries']):
            req=e.get('request',{});u=urlsplit(req.get('url',''));q=parse_qs(u.query)
            if u.hostname in ('demo.rubyplay.com','prrpeu3.com') and u.path=='/launcher' and q.get('gamename'):
                native=q['gamename'][0]
                if not re.fullmatch(r'[A-Za-z0-9_\-]{1,100}',native):raise ValueError('unexpected_native_identity')
                obs={'capture_file':path.name,'entry':i,'host':u.hostname,'native_identity':native,
                     'mode':q.get('mode',[None])[0],'http_status':e.get('response',{}).get('status'),
                     'status':'historical_launch_observation_not_live_validation','session_reused':False}
                launches.append(obs)
                # Exact document/referrer association only; names alone do not bind identity.
                refs=[h.get('value','') for h in req.get('headers',[]) if h.get('name','').lower()=='referer']
                for ref in refs:
                    ru=urlsplit(ref)
                    if ru.hostname=='slotcatalog.com' and '/slots/' in ru.path:
                        key=('slotcatalog',ru.path.rstrip('/').split('/')[-1])
                        record=records.setdefault(key,{'source':'slotcatalog','source_key':key[1],
                            'title':next((n.text() for n in DOM((folder/'2-27.html').read_text(encoding='utf8')).root.walk() if n.tag=='h1'),key[1]),
                            'source_url':'https://slotcatalog.com'+ru.path,'native_identity':None,'aliases':[],
                            'provenance':[],'demo_status':'not_checked_live','qa_status':'not_started_catalogue_gate'})
                        record['native_identity']=native;record['identity_status']='captured_launcher_exact_referrer'
                        record['demo_status']='captured_http_200' if obs['http_status']==200 else 'captured_non_success'
                        proof={'capture_file':path.name,'entry':i,'evidence':'launcher_referrer'}
                        if proof not in record['provenance']:record['provenance'].append(proof)

        # Captured SlotCatalog popup explicitly associates slottranslit with an iframe gamename.
        for i,e in enumerate(har['log']['entries']):
            req=e.get('request',{});u=urlsplit(req.get('url',''));q=parse_qs(u.query)
            if u.hostname!='slotcatalog.com' or not q.get('slottranslit'):continue
            from har_probe import body
            html=body(e).decode('utf8','replace')
            for n in DOM(html).root.walk():
                if n.tag!='iframe':continue
                target=urlsplit(n.attrs.get('src',''));query=parse_qs(target.query)
                if target.hostname!='demo.rubyplay.com' or not query.get('gamename'):continue
                native=query['gamename'][0];slug=q['slottranslit'][0]
                if not re.fullmatch(r'[A-Za-z0-9_\-]{1,100}',native) or not re.fullmatch(r'[A-Za-z0-9_\-]{1,100}',slug):raise ValueError('invalid_catalogue_identity')
                key=('slotcatalog',slug)
                record=records.setdefault(key,{'source':'slotcatalog','source_key':slug,'title':slug,
                    'source_url':'https://slotcatalog.com/es/slots/'+slug,'detail_link_resolved':True,
                    'native_identity':None,'aliases':[],'provenance':[],
                    'demo_status':'not_checked_live','qa_status':'not_started_catalogue_gate'})
                if record['native_identity'] not in (None,native):raise ValueError('conflicting_native_identity')
                record['native_identity']=native;record['identity_status']='captured_popup_slottranslit_to_iframe_gamename'
                record['demo_status']='historical_demo_link_present_not_live_checked'
                proof={'capture_file':path.name,'entry':i,'evidence':'slottranslit_response_iframe'}
                if proof not in record['provenance']:record['provenance'].append(proof)

    links_file=ROOT/'catalogs/official-links.json'
    if links_file.exists():
        for link in json.loads(links_file.read_text(encoding='utf8'))['games']:
            record=records.get(('rubyplay',link['source_key']))
            if record and link.get('native_identity'):
                record.update({'native_identity':link['native_identity'],'identity_status':'official_WP_metadata_game_id_and_public_launcher',
                               'public_demo_url':link['public_demo_url'],'demo_status':'public_link_declared_not_round_validation',
                               'qa_status':'pending_native_protocol'})
                record['provenance'].append({'evidence':'catalogs/official-links.json','post_id':link['post_id']})
    groups=defaultdict(list)
    for record in records.values():groups[norm(record['title'])].append(record)
    candidates=[{'normalized_title':key,'records':[{'source':r['source'],'source_key':r['source_key']} for r in group],
                 'status':'candidate_only_not_native_deduplication'} for key,group in groups.items() if len({r['source'] for r in group})>1]
    sources=[
      {'source':'rubyplay','url':'https://rubyplay.com/reel-winners/','provided_in_har':True,
       'captured_catalog_pages':[1,2,3,4],'declared_pages':6,'declared_catalogue_total':180,'missing_pages':[5,6],
       'termination_verified':False,'complete':False,'live_status':'tls_identity_validation_failed_python_and_windows',
       'native_identity_resolution':'mostly_pending_game_detail_pages','date_basis':'captured HAR pages, not a complete current live snapshot'},
      {'source':'slotcatalog','url':'https://slotcatalog.com/es/soft/Ruby-Play','provided_in_har':True,
       'captured_catalog_pages':[1,2],'captured_views':['captured_initial_GET','SYEAR_AR'],
       'declared_pages':18,'missing_pages':list(range(3,19)),'termination_verified':False,'complete':False,
       'live_status':'http_403_access_stopped'},
      {'source':'slotstemple','url':'https://www.slotstemple.com/ca/free-slots/rubyplay/','provided_in_har':False,
       'source_named_by_user':True,'captured_catalog_pages':[],'declared_pages':None,'termination_verified':False,
       'complete':False,'live_status':'http_403_access_stopped','note':'Distinct website, not SlotCatalog.'}]
    if official:
        sources[0].update({'captured_catalog_pages':[p['page'] for p in official['pages']],
            'declared_pages':official['declared_pages'],'declared_catalogue_total':official['declared_total'],
            'missing_pages':[],'termination_verified':True,'complete':True,'captured_at':official['captured_at'],
            'live_status':'http_200_catalogue_complete_strict_TLS_alternate_official_intermediate',
            'date_basis':'fresh complete official pagination snapshot','tls_fix_added_roots':0,
            'native_identity_resolution':'179 exact native identities in official metadata and public launchers' if links_file.exists() else 'pending'})
    for s in sources:s['source_records']=sum(r['source']==s['source'] for r in records.values())
    resolved={r['native_identity'] for r in records.values() if r['native_identity']}
    freeze={'provider':'rubyplay','frozen_at':now,'stage':'partial_catalogue_frozen_no_gameplay',
        'hybrid_catalogue_complete':False,'gameplay_gate_open':False,'sources':sources,
        'source_record_count':len(records),'resolved_native_identities':len(resolved),
        'unresolved_source_records':sum(r['native_identity'] is None for r in records.values()),
        'candidate_cross_source_title_matches':len(candidates),
        'deduplication_policy':'Merge only an exact demonstrated native identity; source slugs and normalized titles remain separate provisional records.'}
    scope_file=ROOT/'results/scope-authorization.json'
    scope=json.loads(scope_file.read_text(encoding='utf8')) if scope_file.exists() else None
    if scope and scope.get('required_sources_for_gameplay')==['rubyplay'] and official:
        freeze.update({'stage':'official_catalogue_selected_other_sources_deferred','gameplay_gate_open':True,
            'required_sources_for_gameplay':['rubyplay'],'deferred_sources':['slotcatalog','slotstemple'],
            'scope_authorization':'results/scope-authorization.json'})
    out=ROOT/'catalogs';out.mkdir(exist_ok=True)
    durable(out/'source-pages.json',pages);durable(out/'source-records.json',list(records.values()))
    durable(out/'identity-candidates.json',candidates);durable(out/'upcoming.json',upcoming)
    native_groups=defaultdict(list)
    for r in records.values():
        if r['native_identity']:native_groups[r['native_identity']].append({'source':r['source'],'source_key':r['source_key'],'provenance':r['provenance']})
    durable(out/'identity-union.json',{
        'complete':False,'policy':'Canonical groups require native ID evidence; normalized-title candidates never merge records.',
        'canonical_native_groups':[{'native_identity':k,'source_records':v} for k,v in native_groups.items()],
        'unresolved_source_records':[{'source':r['source'],'source_key':r['source_key']} for r in records.values() if not r['native_identity']],
        'candidate_alternative_links':candidates,
        'unassigned_captured_launch_native_identities':sorted({o['native_identity'] for o in launches}-set(native_groups))})
    candidate_keys={(r['source'],r['source_key']) for g in candidates for r in g['records']}
    durable(out/'observed-source-only.json',{
        'status':'provisional_not_proof_of_exclusivity','reason':'Incomplete source pagination and unresolved native IDs.',
        'records':[{'source':r['source'],'source_key':r['source_key'],'title':r['title'],'source_url':r['source_url']}
                   for k,r in records.items() if k not in candidate_keys]})
    durable(out/'captured-launch-observations.json',launches);durable(out/'catalogue-freeze.json',freeze)
    blocks=[]
    for p in (ROOT/'private'/'catalog-snapshots').glob('*/*.meta.json'):
        m=json.loads(p.read_text(encoding='utf8'));blocks.append({k:m[k] for k in ('source','key','url','state','status','curl_exit','error_type','bytes','sha256') if k in m})
    durable(out/'access-observations.json',blocks)
    durable(ROOT/'sources'/'har-manifest.json',[{k:h[k] for k in ('file','sha256','bytes','entries','websocket_messages')} for h in index])
    live_file=ROOT/'results/live-summary.json'
    live=json.loads(live_file.read_text(encoding='utf8')) if live_file.exists() else {}
    report={'provider':'rubyplay','updated_at':now,'status':'official_scope_protocol_preparation' if freeze['gameplay_gate_open'] else 'blocked_catalogue_incomplete','catalogue':freeze,
      'verified_games':0,'verified_modes':0,'new_gameplay_requests_sent':0,'sessions_from_har_reused':0,
      'evidence_manifest':'results/evidence-manifest.json',
      'historical_launch_observations':launches,'current_roots':[],'uncertain_roots':[],
      'incidents':[{'type':'catalogue_access_block','source':s['source'],'status':s['live_status']} for s in sources if not s['complete']],
      'historical_incidents':([{'source':'rubyplay','type':'TLS_chain_validation_failed','resolved':True,
          'resolution':'Official alternate intermediate to existing trusted root; strict hostname and full-chain validation retained.',
          'evidence':'catalogs/tls-correction.json'}] if official else []),
      'pending':([] if official else ['Archive missing official pages 5–6 with valid TLS.'])+['Archive SlotCatalog pages 3–18 and verify filter/view continuity and final page.',
                 'Archive SlotTemple catalogue independently; its total and termination are unverified.',
                 'Resolve native identities before merging source records.','Only then validate fresh public demo launchers and prepare protocol/cost bindings.'],
      'limitations':['No verified complete hybrid catalogue.','Source-record counts are not unique native-game counts.',
                     'Captured HTTP 200 does not prove current availability or a settled round.','No financial protocol or game modes were executed during this stage.']}
    for key in ('status','verified_games','verified_modes','new_gameplay_requests_sent','current_roots','uncertain_roots'):
        if key in live:report[key]=live[key]
    if scope:report['current_scope']=scope
    if scope and scope.get('required_sources_for_gameplay')==['rubyplay']:
        report['pending']=['Process remaining linked official demos with per-bundle native protocol bindings; normal and all declared modes.',
                           'One upcoming official listing has no usable demo metadata. SlotCatalog and SlotTemple deferred to user.']
        report['limitations']=['Hybrid catalogue incomplete and deferred by user.','Only individually settled modes are verified; native identities and demo links are not round coverage.']
    report['protocol_observations']=[
      {'native_identity':'rp_90','source':'SlotCatalog captured demo','mode_observed':'offline',
       'launcher_host':'demo.rubyplay.com','client_asset_family':'yohoho-rtp96',
       'remote_settlement_demonstrated':False,'notes':'Mode literal only; native calculation and continuations not executed or verified.'},
      {'native_identity':'rp_240','source':'RubyPlay captured launcher','mode_observed':'fun',
       'launcher_host':'prrpeu3.com','remote_settlement_demonstrated':False,
       'notes':'Captured init has HAR status 0 and an 881-byte JSON body. Initialization configuration is present; it proves no paid round or settlement.'}]
    durable(ROOT/'results'/'provider-report.json',report)
    print(json.dumps({'source_record_count':len(records),'per_source':{s['source']:s['source_records'] for s in sources},
        'official_cards_by_page':[p['card_count'] for p in pages if p['source']=='rubyplay'],
        'slotcatalog_cards_by_view':[(p['page'],p['view'],p['card_count']) for p in pages if p['source']=='slotcatalog'],
        'resolved_native_identities':len(resolved),'candidate_title_matches':len(candidates),'launches':launches},ensure_ascii=False))

if __name__=='__main__':main()
