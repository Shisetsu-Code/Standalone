"""Fixed-host public ELK demo client. No captured session or wager retries."""
import hashlib,re,time,secrets
from urllib.parse import urlencode,urlparse,parse_qs
import xml.etree.ElementTree as ET
import requests
from elk_protocol import parse_xml,redact_xml,validate_fresh_demo

STATIC='https://static-stage.contentmedia.eu'
CAPI='https://gc5-stage.contentmedia.eu/capi'

class Elk:
    def __init__(self,game,save):
        if not re.fullmatch(r'\d+',game['id']):raise ValueError('invalid_id')
        self.game=game;self.save=save;self.trace=[];self.session=requests.Session();self.seq=0;self.nonce=str(time.time_ns()//1000000)+str(secrets.randbelow(10));self.key=None
        self.session.headers.update({'User-Agent':'ELK-Demo-QA/1.0','Origin':STATIC,'X-CAPI-VERSION':'2.0'})

    def get(self,url):
        response=self.session.get(url,timeout=45,allow_redirects=False);response.raise_for_status();return response

    def open(self):
        query={'gameid':self.game['id'],'operatorid':'44','mode':'demo','currency':'EUR','device':'desktop','language':'en_gb','xdm':self.game.get('xdm','0')}
        if self.game.get('direct_name'):
            query.update(gamename=self.game['direct_name'],capi=CAPI,papi='https://papi-stage.contentmedia.eu')
            target=urlparse(STATIC+'/ecf3/index.html?'+urlencode(query))
        else:
            response=self.get('https://gamelauncher-stage.contentmedia.eu/1.0/game/?'+urlencode(query))
            target=urlparse(response.headers.get('Location',''))
        q=parse_qs(target.query)
        if target.scheme!='https' or target.hostname!='static-stage.contentmedia.eu' or target.path not in ('/ecf3/index.html','/ecf2/index.html','/ecf/index.html'):raise ValueError('unverified_public_launcher')
        for field,value in {'gameid':self.game['id'],'operatorid':'44','mode':'demo','currency':'EUR','capi':CAPI}.items():
            if q.get(field)!=[value]:raise ValueError('launcher_contract:'+field)
        name=q.get('gamename',[''])[0]
        if not re.fullmatch(r'[a-z0-9_-]+',name):raise ValueError('unverified_game_name')
        framework=target.path.split('/')[1]
        game_js=self.get(STATIC+'/'+name+'/version.js').text;ecf_js=self.get(STATIC+'/'+framework+'/version.js').text
        def version(text,field):
            match=re.search(r'\b'+field+r'\s*=\s*["\x27]([0-9]+)["\x27]',text)
            if not match:raise ValueError('public_build_missing:'+field)
            return match[1]
        self.session.headers.update({'X-CLIENT-VERSION':version(game_js,'game_revision'),'X-ECF-VERSION':version(ecf_js,'ecf_revision')})
        self.launch={'gameid':self.game['id'],'gamename':name,'framework':framework,'mode':'demo','operatorid':'44','currency':'EUR','capi':CAPI,'client_revision':self.session.headers['X-CLIENT-VERSION'],'ecf_revision':self.session.headers['X-ECF-VERSION']}
        self.extsession=str(time.time_ns()//1000000+secrets.randbelow(10000))
        init=self.call('init',{'opid':'44','extsession':self.extsession,'cur':'EUR','desktopmode':'true','lang':'en_gb','screenres':'1920,1080,1718,966','extjur':'NA'})
        validate_fresh_demo(init)
        self.uses_bmode=init.find('betlevels').get('bmode')=='true'
        self.min_spin_delay_ms=int(init.findtext('gamesession/minspindelay','0'))
        if not 0<=self.min_spin_delay_ms<=30000:raise ValueError('unsupported_native_spin_delay')
        self.key=init.findtext('gamesession/id')
        if not self.key:raise ValueError('demo_session_missing')
        return init

    def call(self,method,attributes):
        if method not in ('init','purchase','checkwin'):raise ValueError('unsupported_method')
        self.seq+=1;request=ET.tostring(ET.Element('request',attributes),encoding='unicode')
        rid=max(time.time_ns()//1000000*10+self.seq%10,getattr(self,'last_rid',0)+1);self.last_rid=rid
        step={'method':method,'request_id':'request-'+hashlib.sha256(str(rid).encode()).hexdigest()[:20],'request':redact_xml(request),'status':'sending','started':time.time()};self.trace.append(step);self.save(self)
        start=time.monotonic()
        try:
            response=self.session.post(CAPI+'/'+self.game['id']+'/play/'+method+'?gl=true&standalone=false&iframe=false',data=('<?xml version="1.0"?>'+request).encode('utf8'),headers={'Content-Type':'text/xml; charset=utf-8','X-CAPI-RID':str(rid)+':1'},timeout=60,allow_redirects=False)
            step.update(http_status=response.status_code,elapsed_ms=round((time.monotonic()-start)*1000),status='received')
            if response.text.strip().startswith('<response'):step['response']=redact_xml(response.text)
            self.save(self)
            response.raise_for_status();root=parse_xml(response.text)
            renewed=root.findtext('gamesession/id')
            if renewed:self.key=renewed
            self.save(self)
            return root
        except Exception:
            step['status']='failed_or_uncertain';self.save(self);raise

    def purchase(self,control):
        attrs={'gamesession':self.key,'amount':control['amount'],'cur':'EUR','bmode':control['mode'],'betdetails':'','betlevel':control['betlevel'],'pmode':'click-s0','orientation':'landscape','sound':'bgeffect','monetaryunit':'money','gamespeed':'normal'}
        if not self.uses_bmode:
            if control['mode']!='DEF':raise ValueError('non_normal_disabled')
            attrs.pop('bmode')
        if control.get('variant'):attrs['variant']=control['variant']
        delay=getattr(self,'min_spin_delay_ms',0)/1000
        pause=delay+(0.1 if delay else 0)-(time.monotonic()-getattr(self,'last_purchase_finished',getattr(self,'last_purchase_started',0)))
        if pause>0:time.sleep(pause)
        self.last_purchase_started=time.monotonic()
        try:return self.call('purchase',attrs)
        finally:self.last_purchase_finished=time.monotonic()

    def check(self,reply):
        return self.call('checkwin',{'gamesession':self.key,'roundid':reply.findtext('roundid') or '0'})
