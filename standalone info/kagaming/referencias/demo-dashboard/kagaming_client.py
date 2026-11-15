"""Fresh anonymous public-demo sessions; private journals never served by HTTP."""
import hashlib,json,re,secrets,time,uuid,os
from pathlib import Path
from kagaming_core import sign_context,integer,sanitize
from kagaming_browser_bridge import browser_post

PRIVATE=Path(__file__).resolve().parent.parent/'kagaming-private'

class NativeDemoError(ValueError):
    def __init__(self,record):
        super().__init__('native_demo_error');self.record=record

def validate_family(game,source):
    if game['gameType']=='slots':return
    if game['id']=='ChickenQuest':
        from kagaming_chicken import SOURCE_SHA256
        if game['gameType']!='other' or hashlib.sha256(source.encode('utf8')).hexdigest()!=SOURCE_SHA256:raise ValueError('family_protocol_requires_review')
        return
    if game['id'] in ('HomeRunDerby','BonusPoker'):
        from kagaming_interactive import SOURCE_SHA256
        family='other' if game['id']=='HomeRunDerby' else 'vpoker'
        if game['gameType']!=family or hashlib.sha256(source.encode('utf8')).hexdigest()!=SOURCE_SHA256[game['id']]:raise ValueError('family_protocol_requires_review')
        return
    bindings=json.loads((Path(__file__).parent/'kagaming/reference/family-bindings.json').read_text(encoding='utf8'))
    proof=bindings.get(game['id'],{})
    if proof.get('family')!=game['gameType'] or proof.get('action')!='rmp_spin' or proof.get('source_sha256')!=hashlib.sha256(source.encode('utf8')).hexdigest():raise ValueError('family_protocol_requires_review')

def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    for attempt in range(10):
        try:os.replace(temp,path);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.05)

def claim_game(path,gid,now=None):
    now=time.time() if now is None else now;path=Path(path)
    old=json.loads(path.read_text()) if path.exists() else {}
    if now-old.get('last_started_at',-120)<120:raise ValueError('game_cadence_not_elapsed')
    save(path,{'last_game':gid,'last_started_at':now,'minimum_interval_seconds':120})

def ensure_not_sent(path):
    if Path(path).exists():raise ValueError('existing_request_must_not_be_replayed')

def minimum_profile(init,source):
    prices=None;purchase_via_atb=False
    match=re.search(r'Uc:function\(a,\s*b\)\{return\s+(?:(\d+)\*)?a\*\s*b\}',source)
    formula=match.group(0) if match else None
    multiplier=int(match.group(1) or 1) if match else None
    sel=min(integer(x) for x in init['ase']);cps=min(integer(x) for x in init['cup']);dn=min(init['dn'])
    if sel<=0 or cps<=0 or dn<=0:raise ValueError('invalid_native_minimum')
    if match:cost=multiplier*sel*cps
    elif re.search(r'Uc:function\(a,b\)\{return\s+(?:(\d+)\*\s*)?b\}',source):
        factor=int(re.search(r'Uc:function\(a,b\)\{return\s+(?:(\d+)\*\s*)?b\}',source).group(1) or 1)
        if factor<=0:raise ValueError('invalid_source_price')
        cost=factor*cps;formula='Uc(sel,cps) -> '+str(factor)+'*cps (selection-independent)'
    elif 'A.zb().Ig("HotCoinBF",this)' in source and 'Uc:function(a,b,d){a*=b;1<=d&&9>=d&&(a*=this.xNa[d-1]);return a}' in source:
        table=re.search(r'this\.xNa=\[([0-9,]+)\]',source)
        factors=[int(x) for x in table.group(1).split(',')] if table else []
        if len(factors)!=9 or min(factors)<=1:raise ValueError('unreviewed_hotcoin_menu')
        cost=sel*cps;prices=[1]+factors;prices=[p*sel for p in prices];purchase_via_atb=True
        formula='HotCoinBF Uc(sel,cps,atb) -> sel*cps*xNa[atb-1] for atb1..9; normal atb0'
    elif 'Uc:function(a,b){return this.PR*b}' in source and re.search(r'new \(Hd\.extend\(\{PR:(\d+),',source) and not re.search(r'this\.PR\s*(?:=|\+\+|--|[+*/-]=)',source):
        price=int(re.search(r'new \(Hd\.extend\(\{PR:(\d+),',source).group(1))
        if price<=0:raise ValueError('invalid_source_price')
        cost=price*cps;formula='Uc(sel,cps) -> constant PR*cps; PR='+str(price)
    elif 'Uc:function(a,b){return this.Z6*b}' in source and re.search(r'new \(Hd\.extend\(\{Z6:(\d+),',source) and not re.search(r'this\.Z6\s*(?:=|\+\+|--|[+*/-]=)',source):
        price=int(re.search(r'new \(Hd\.extend\(\{Z6:(\d+),',source).group(1))
        if price<=0:raise ValueError('invalid_source_price')
        cost=price*cps;formula='Uc(sel,cps) -> constant Z6*cps; Z6='+str(price)
    elif 'Uc:function(a,b,d){return 0<=d&&5>d?this.PR[d]*b:this.PR[0]*b}' in source and 'Jg:function(){return this.Uc(this.gd(),uc.Cg(),4)}' in source:
        table=re.search(r'new \(Hd\.extend\(\{PR:\[([0-9,]+)\]',source)
        if not table or sel!=5:raise ValueError('unreviewed_price_table')
        prices=[int(x) for x in table.group(1).split(',')]
        if len(prices)!=5:raise ValueError('unreviewed_price_table')
        cost=prices[0]*cps;formula='Uc(sel,cps,atb) -> PR[atb]*cps; engine fo -> request.atb; PR='+str(prices)
    else:raise ValueError('unreviewed_game_cost_formula')
    result={'sel':sel,'cps':cps,'dn':dn,'atb':0,'cost_native':cost,'cost_formula':formula,'source_sha256':hashlib.sha256(source.encode('utf8')).hexdigest()}
    if prices is not None:result['ante_costs_native']=[p*cps for p in prices]
    if purchase_via_atb:result['purchase_via_atb']=True
    if 'A.zb().Ig("Shopping",this)' in source:result['choice_family']='shopping'
    if 'A.zb().Ig("AlienDairy",this)' in source:result['choice_family']='alien_dairy'
    return result

def position_for_step(profile,previous=None):
    if profile.get('choice_family')=='alien_dairy':
        if previous is None:return None
        if previous.get('fsr',0)>0:return [0]
        raise ValueError('alien_dairy_no_pending_pick')
    if profile.get('choice_family')=='shopping':
        if previous is None:return [0]
        stage=previous.get('sm',[None])[0]
        if stage==0:return [0]
        if stage in (1,2):return [2]
        raise ValueError('shopping_closed_or_unknown_stage')
    return profile.get('position') if previous is None else None

def mode_profiles(init,source,buy_feature):
    if 'A.zb().Ig("PhilosopherRoulette",this)' in source:
        from kagaming_philosopher import plans
        return plans('PhilosopherRoulette',init,source,(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes())
    if 'A.zb().Ig("AmericanRoulette",this)' in source:
        from kagaming_american import plans
        return plans(init,source)
    if 'A.zb().Ig("ChickenQuest",this)' in source:
        from kagaming_chicken import plans
        return plans('ChickenQuest',init,source,(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes())
    if 'A.zb().Ig("PenaltyShootout",this)' in source:
        from kagaming_penalty import plans
        return plans(init,source,(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes())
    for game in ('HomeRunDerby','BonusPoker'):
        if 'A.zb().Ig("'+game+'",this)' in source:
            from kagaming_interactive import plans
            return plans(game,init,source,(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes())
    if 'A.zb().Ig("FortuneSkyLanterns",this)' in source:
        from kagaming_lanterns import plans
        return plans(init,source)
    if 'A.zb().Ig("FrenchRoulette",this)' in source:
        from kagaming_roulette import plans
        return plans(init,source)
    base=minimum_profile(init,source);modes=[dict(base,kind='normal',key='normal')]
    if base.get('choice_family')=='shopping':modes[0]['position']=[0]
    for atb,cost in enumerate(base.get('ante_costs_native',[])[1:],1):
        kind='buy' if base.get('purchase_via_atb') else 'ante';key=('buy-atb-' if kind=='buy' else 'ante-')+str(atb)
        modes.append(dict(base,kind=kind,key=key,atb=atb,cost_native=cost))
    if buy_feature and not base.get('purchase_via_atb'):
        match=re.search(r'qja:function\(a,b,d,e\)\{return\s+(\d+)\*this\.Uc\(a,b,d,e\)\}',source)
        if not match:raise ValueError('unreviewed_purchase_price')
        engine=(Path(__file__).parent/'kagaming/reference/game.min.2090.js').read_bytes()
        if hashlib.sha256(engine).hexdigest()!='6cf1bdace2d5fb0a889364ad05fa3a3a31ed2fc37aa79b36be4ee71a6e49a0f2':raise ValueError('purchase_action_binding_changed')
        multiplier=int(match.group(1))
        if multiplier<=1:raise ValueError('invalid_purchase_multiplier')
        modes.append(dict(base,kind='buy',key='buy-1',position=[1],cost_native=base['cost_native']*multiplier,purchase_multiplier=multiplier))
    return modes

class DemoClient:
    def __init__(self,gid):
        self.gid=gid;self.user=str(secrets.randbelow(900000000)+100000000);self.folder=PRIVATE/'sessions'/(gid+'-'+uuid.uuid4().hex)
        self.context={'dt':'Python QA client','dv':'3.11','av':'1.0.268 (2090)','idv':hashlib.sha256(uuid.uuid4().bytes).hexdigest(),'lg':'es','do':'Windows','as':'','ak':'accessKey'}
        self.sequence=0
    def request(self,path,body,journal):
        ensure_not_sent(journal)
        signed=sign_context(json.dumps(body,separators=(',',':'),ensure_ascii=False),self.context,int(time.time()*1000))
        record={'status':'sending','request':body,'path':path,'started_at':time.time()};save(journal,record)
        try:
            r=browser_post('https://rmpdemo.kaga88.com'+path+'?ak=accessKey&cr=USD&m=0&u='+self.user,body,json.dumps(signed,separators=(',',':')))
            record.update(status='received',http_status=r.status_code)
            if r.status_code!=200:raise ValueError('demo_http_'+str(r.status_code))
            data=r.json();record['response']=data;save(journal,record)
            if data.get('e') is not False or data.get('ec')!=0:raise NativeDemoError(record)
            return record
        except Exception as e:
            record['error']=str(e);save(journal,record);raise
    def start(self):
        claim_game(PRIVATE/'cadence.json',self.gid)
        body={'un':self.user,'pn':'demo','ak':'accessKey','gn':self.gid,'loc':'es','to':'123','cr':'USD','gm':0,'tb':None,'mi':-1,'mc':0}
        step=self.request('/kaga/rmp/startGame',body,self.folder/'initialization.json');data=step['response']
        if not data.get('si') or not data.get('un'):raise ValueError('missing_new_demo_session')
        self.context.update(u=data['un'],c=data['si']);self.initialization=data
        save(self.folder/'session.json',{'user':self.user,'context':self.context,'game':self.gid})
        return data
    def spin(self,profile,journal,position=None):
        self.sequence+=1;body={'gn':self.gid,'sel':profile['sel'],'sid':int(time.time()*1000)%2000000000+self.sequence,'cps':profile['cps'],'atb':profile['atb'],'dn':profile['dn']}
        if position is not None:body['pos']=position
        return self.request('/kaga/command/spin',body,journal)
