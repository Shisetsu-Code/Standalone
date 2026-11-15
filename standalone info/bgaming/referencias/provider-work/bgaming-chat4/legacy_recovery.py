"""Restore only this suite's received fresh legacy context, preserving public ID aliases."""
import json,re,http.cookiejar,urllib.request
from run_demo_qa import Demo,ROOT,PRIVATE,trusted
from resume_frenzy import restore_aliases
def rejection_request_matches(data,event,clean):
 if 'last_request' in data:return clean(data['last_request'])==event['request']
 op=data.get('operation',{})
 return op.get('status')=='http_rejection' and op.get('command')==event['request'].get('command') and op.get('http_status')==event.get('status') and type(event.get('status')) is int
def restore(gid):
 if not re.fullmatch('[A-Za-z0-9_-]+',gid):raise ValueError('Invalid identifier')
 report=json.loads((ROOT/'live'/(gid+'.json')).read_text(encoding='utf8'));credentials=json.loads((PRIVATE/(gid+'.session.json')).read_text(encoding='utf8'))
 if not credentials.get('fresh_demo') or credentials['game_id']!=gid or credentials['operation']['status']!='received':raise ValueError('Only a received fresh QA context can be resumed')
 demo=Demo(report['game']);demo.api=trusted(credentials['api']);demo.page=credentials['page'];demo.csrf_name=credentials['csrf_name'];demo.csrf_value=credentials['csrf_value'];demo.series=credentials['series'];demo.last_response=credentials['last_response'];demo.events=report['events'];demo.money_checks=report.get('checks',[]);restore_aliases(demo.clean,demo.events,demo.last_response,demo.series)
 if demo.clean.clean(demo.last_response)!=report['events'][-1]['response']:raise ValueError('Private/public last response differs; no replay')
 jar=next(h.cookiejar for h in demo.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in credentials['cookies']:jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 return demo,report

def restore_rejected_continuation(gid,status,code,description,command,options):
 """Restore only an exact classified rejection; retain both accepted state and rejection."""
 if not re.fullmatch('[A-Za-z0-9_-]+',gid):raise ValueError('Invalid identifier')
 report=json.loads((ROOT/'live'/(gid+'.json')).read_text(encoding='utf8'));data=json.loads((PRIVATE/(gid+'.session.json')).read_text(encoding='utf8'));events=report.get('events',[])
 if not data.get('fresh_demo') or data['game_id']!=gid or data.get('operation',{}).get('status')!='http_rejection' or len(events)<2:raise RuntimeError('Not a classified fresh QA rejection')
 last=events[-1]
 if last.get('status')!=status or last.get('response',{}).get('errors')!=[{'code':code,'desc':description}] or last['request'].get('command')!=command or last['request'].get('options')!=options:raise RuntimeError('Rejected continuation differs from the source correction')
 currency=events[0]['response']['options']['currency']
 if currency.get('code')!='FUN' or currency.get('subunits')!=100:raise RuntimeError('Not native FUN QA')
 demo=Demo(report['game']);demo.api=trusted(data['api']);demo.page=data['page'];demo.csrf_name=data['csrf_name'];demo.csrf_value=data['csrf_value'];demo.series=data['series'];demo.last_response=data['last_response'];demo.events=events;demo.money_checks=report.get('checks',[]);restore_aliases(demo.clean,events[:-1],demo.last_response,demo.series)
 if demo.clean.clean(demo.last_response)!=events[-2]['response'] or not rejection_request_matches(data,last,demo.clean.clean):raise RuntimeError('Accepted/rejected private/public checkpoints differ')
 jar=next(h.cookiejar for h in demo.opener.handlers if isinstance(h,urllib.request.HTTPCookieProcessor))
 for c in data['cookies']:jar.set_cookie(http.cookiejar.Cookie(version=0,name=c['name'],value=c['value'],port=None,port_specified=False,domain=c['domain'],domain_specified=True,domain_initial_dot=c['domain'].startswith('.'),path=c['path'],path_specified=True,secure=c['secure'],expires=c['expires'],discard=c['expires'] is None,comment=None,comment_url=None,rest={}))
 return demo,report

def adopt_observed_init(demo,report,gid):
 rb=json.loads((PRIVATE/'readback'/(gid+'.json')).read_text(encoding='utf8'));r=rb['response'];old=demo.last_response
 if rb['status']!=200 or rb['time']<=report['events'][-1]['time'] or rb['request'].get('command')!='init' or rb['request'].get('extra_data',{}).get('round_series_id')!=demo.series or r.get('flow',{}).get('round_id')!=old['flow']['round_id'] or r.get('flow',{}).get('state')!=old['flow']['state'] or r.get('options',{}).get('currency',{}).get('code')!='FUN':raise RuntimeError('Init observation does not prove the same pending FUN context')
 if r['balance']!=old['balance']:report.setdefault('provider_state_observations',[]).append(dict(kind='native_init_balance_refresh',before_native=old['balance'],after_native=r['balance'],event=len(demo.events),note='Provider response retained round/state and changed FUN balance; not a gameplay win or local balance edit'))
 demo.events.append(dict(time=rb['time'],request=demo.clean.clean(rb['request']),response=demo.clean.clean(r),status=rb['status'],response_sha256=rb['response_sha256'],kind='non_wagering_init_reconciliation'));demo.last_response=r;return r
