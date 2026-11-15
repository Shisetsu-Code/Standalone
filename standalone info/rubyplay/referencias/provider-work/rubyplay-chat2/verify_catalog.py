"""Offline integrity and scope audit; never creates a session or uses network."""
import hashlib,json,re
from pathlib import Path
from har_probe import ROOT

PUBLIC_DIRS=('catalogs','sources','results')
SECRETS=re.compile(r'(?i)(?:bearer\s+[A-Za-z0-9._-]{10,}|(?:launch_token|session_id|access_token|auth_token|nonce|signature)=[A-Za-z0-9._-]+)')

def validate_gate(report):
    catalogue=report['catalogue']
    if catalogue['hybrid_catalogue_complete']:
        if not all(s['complete'] and s['termination_verified'] for s in catalogue['sources']):
            raise ValueError('incomplete_source_cannot_open_gameplay_gate')
    if catalogue['gameplay_gate_open']:
        required=catalogue.get('required_sources_for_gameplay',[s['source'] for s in catalogue['sources']])
        if not required or not all(s['complete'] and s['termination_verified'] for s in catalogue['sources'] if s['source'] in required):
            raise ValueError('required_source_incomplete')
        if set(required)-{s['source'] for s in catalogue['sources']}:raise ValueError('required_source_absent')
    if not catalogue['gameplay_gate_open'] and report['new_gameplay_requests_sent']:
        raise ValueError('gameplay_before_catalogue_gate')

def validate_complete_source(source,pages):
    if not source['complete']:return
    selected=[p for p in pages if p['source']==source['source']]
    expected=list(range(1,source['declared_pages']+1))
    if sorted(p['page'] for p in selected)!=expected:raise ValueError('complete_source_missing_page')
    cursor=1;identities=[]
    for page in sorted(selected,key=lambda p:p['page']):
        start,end=page['range']
        if start!=cursor or end-start+1!=len(page['cards']):raise ValueError('complete_source_range_gap')
        cursor=end+1;identities.extend(r['source_key'] for r in page['cards'])
    if not source['termination_verified'] or cursor-1!=source['declared_catalogue_total']:
        raise ValueError('complete_source_unverified_end')
    if len(identities)!=len(set(identities)):raise ValueError('complete_source_duplicate_identity')

def audit(manifest=False):
    report=json.loads((ROOT/'results/provider-report.json').read_text(encoding='utf8'))
    validate_gate(report)
    rows=json.loads((ROOT/'catalogs/source-records.json').read_text(encoding='utf8'))
    pages=json.loads((ROOT/'catalogs/source-pages.json').read_text(encoding='utf8'))
    for source in report['catalogue']['sources']:validate_complete_source(source,pages)
    if len(rows)!=len({(r['source'],r['source_key']) for r in rows}):raise ValueError('duplicate_source_record')
    if len(rows)!=report['catalogue']['source_record_count']:raise ValueError('record_count_mismatch')
    for page in pages:
        if len(page['cards'])!=page['card_count']:raise ValueError('card_count_mismatch')
        raw=ROOT/page['archive_response'] if page.get('archive_response') else ROOT/'private/har-documents'/page['capture_document']
        if not raw.resolve().is_relative_to(ROOT):raise ValueError('source_page_path_escape')
        if hashlib.sha256(raw.read_bytes()).hexdigest()!=page['captured_body_sha256']:raise ValueError('captured_body_changed')
    public_files=[]
    for name in PUBLIC_DIRS:
        for path in (ROOT/name).glob('*.json'):
            if path.name in ('evidence-manifest.json','verification.json'):continue
            text=path.read_text(encoding='utf8');data=json.loads(text)
            if SECRETS.search(text):raise ValueError('credential_pattern_in_public_export:'+path.name)
            def visit(value):
                if isinstance(value,dict):
                    if any(k.lower() in ('cookies','headers','postdata','authorization','raw_body') for k in value):raise ValueError('raw_secret_field')
                    for v in value.values():visit(v)
                elif isinstance(value,list):
                    for v in value:visit(v)
            visit(data)
            public_files.append(path)
    if manifest:
        index=json.loads((ROOT/'results/evidence-manifest.json').read_text(encoding='utf8'))
        for row in index['files']:
            path=ROOT/row['path']
            if not path.resolve().is_relative_to(ROOT):raise ValueError('manifest_path_escape')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('manifest_hash_mismatch')
    return {'passed':True,'catalogue_complete':report['catalogue']['hybrid_catalogue_complete'],
            'gameplay_gate_open':report['catalogue']['gameplay_gate_open'],
            'source_records_checked':len(rows),'source_pages_checked':len(pages),
            'public_json_files_checked':len(public_files),'gameplay_requests':report['new_gameplay_requests_sent'],
            'native_identity_merge_policy':'exact evidence only; title candidates retained separately'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--manifest',action='store_true');args=p.parse_args()
    print(json.dumps(audit(args.manifest)))
