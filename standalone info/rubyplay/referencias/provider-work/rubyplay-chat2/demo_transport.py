"""Isolated public-demo setup reads, with durable private journals and strict TLS."""
from datetime import datetime,timezone
import hashlib,json,ssl,os,re
from urllib.request import Request,build_opener,HTTPSHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit
from pathlib import Path
from har_probe import ROOT,safe_url
from catalog_network import durable,NoRedirect

def native_read(url,folder,key,allowed_hosts,payload=None,round_plan=None):
    financial=round_plan is not None
    if financial:
        native=round_plan.get('game','rp_222')
        if not re.fullmatch(r'rp_[0-9]+',native):raise ValueError('native_game_binding_not_reviewed')
        native_folder=ROOT/('private/live/'+native+'-preparation')
        if Path(folder).resolve()!=native_folder.resolve():raise ValueError('native_journal_game_mismatch')
        plan=json.loads((native_folder/'next-request.private').read_text(encoding='utf8'))
        if plan!=round_plan or plan.get('state')!='ready' or plan['key']!=key or plan['payload']!=payload:raise ValueError('native_plan_not_current')
        if native=='rp_222':actions=('spin','respin','buy_feature')
        else:
            binding=json.loads((ROOT/('results/'+native+'-binding.json')).read_text(encoding='utf8'))
            if binding.get('state')!='init_binary_verified_normal_prepared' or binding.get('source_sha256')!=plan['source_sha256']:raise ValueError('native_game_binding_not_reviewed')
            actions=binding.get('reviewed_transport_actions',[])
        if url!='https://srv.prrpeu3.com/gameserver/demo' or payload.get('action') not in actions:raise ValueError('unbound_native_action')
        if not json.loads((ROOT/'results/provider-report.json').read_text())['catalogue']['gameplay_gate_open']:raise ValueError('inventory_gate_closed')
        from prepare_client import source_text
        source=source_text((native_folder/'game-js.body.private').read_bytes())
        if hashlib.sha256(source.encode()).hexdigest()!=plan['source_sha256']:raise ValueError('native_source_changed')
    elif payload is not None and payload.get('action')!='init':raise ValueError('setup_transport_only_accepts_init')
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in allowed_hosts or u.username or u.password:raise ValueError('unproved_public_demo_owner')
    if (ROOT/'private/network'/(u.hostname+'.blocked.json')).exists():raise RuntimeError('provider_access_block_retained')
    folder=Path(folder)
    if not folder.resolve().is_relative_to(ROOT):raise ValueError('journal_outside_isolation')
    folder.mkdir(parents=True,exist_ok=True);journal=folder/(key+'.journal.json')
    if journal.exists():raise RuntimeError('request_already_journaled_no_replay')
    proof=json.loads((ROOT/'private/network/rubyplay-tls-chain-fixed.json').read_text(encoding='utf8'))
    cafile=ROOT/proof['ca_file']
    if not proof['passed'] or hashlib.sha256(cafile.read_bytes()).hexdigest()!=proof['ca_sha256']:raise ValueError('TLS_pin_changed')
    ctx=ssl.create_default_context(cafile=str(cafile))
    if not ctx.check_hostname or ctx.verify_mode!=ssl.CERT_REQUIRED:raise ValueError('TLS_must_be_strict')
    intent={'key':key,'purpose':'public_fun_native_round' if financial else ('public_demo_setup_POST_init' if payload is not None else 'public_demo_setup_GET'),'financial_action':financial,'started_at':datetime.now(timezone.utc).isoformat(),
            'url':safe_url(url),'state':'intent_before_send','pid':os.getpid()}
    encoded=None if payload is None else json.dumps(payload,separators=(',',':')).encode()
    if encoded is not None:
        (folder/(key+'.request.private')).write_bytes(encoded)
        intent['request_sha256']=hashlib.sha256(encoded).hexdigest()
    # Exclusive, permanent claim closes the check/write race across workers.
    # A crash leaves evidence for review instead of making the action replayable.
    try:
        with (folder/(key+'.claim')).open('x',encoding='utf8') as claim:
            claim.write(json.dumps({'financial_action':financial,'pid':os.getpid()}));claim.flush();os.fsync(claim.fileno())
    except FileExistsError as error:raise RuntimeError('request_already_claimed_no_replay') from error
    durable(journal,intent)
    req=Request(url,data=encoded,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/json,application/javascript',**({'Content-Type':'application/json'} if encoded is not None else {})})
    try:
        with build_opener(HTTPSHandler(context=ctx),NoRedirect()).open(req,timeout=45) as response:
            data=response.read(20_000_001)
            if len(data)>20_000_000:raise ValueError('native_source_too_large')
            status=response.status;mime=response.headers.get('Content-Type','')
    except HTTPError as e:
        status=e.code;data=e.read(1_000_000);mime=e.headers.get('Content-Type','')
    except Exception as e:
        durable(journal,{**intent,'state':'transport_error_no_replay','error_type':type(e).__name__,'error':str(e)[:300]})
        if isinstance(getattr(e,'reason',e),ssl.SSLError):
            durable(ROOT/'private/network'/(u.hostname+'.blocked.json'),{**intent,'block_type':'TLS_failure_no_retry','error_type':type(e).__name__})
        raise
    (folder/(key+'.body.private')).write_bytes(data)
    result={**intent,'state':'received','status':status,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content_type':mime,
            'finished_at':datetime.now(timezone.utc).isoformat()}
    durable(journal,result)
    if status in (403,429,503):durable(ROOT/'private/network'/(u.hostname+'.blocked.json'),result)
    print(json.dumps({k:result[k] for k in ('key','status','bytes','financial_action')}),flush=True)
    return result,data

if __name__=='__main__':
    links=json.loads((ROOT/'catalogs/official-links.json').read_text(encoding='utf8'))
    game=next(r for r in links['games'] if r.get('native_identity')=='rp_222')
    native_read(game['public_demo_url'],ROOT/'private/live/rp_222-preparation','launcher',{'prrpeu3.com'})
