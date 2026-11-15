"""Fixed public-demo transport. No casino credentials or captured sessions."""
import re
import time
import requests
from hacksaw_protocol import redact
from hacksaw_contracts import native_extra

STATIC='https://static-live.hacksawgaming.com/'
API='https://rgs-demo.hacksawgaming.com/api/play/'


class Hacksaw:
    def __init__(self,game_id):
        if not re.fullmatch(r'[0-9]+',str(game_id)):raise ValueError('invalid_game_id')
        self.game_id=str(game_id);self.http=requests.Session();self.trace=[];self.seq=0
        r=self.http.get(STATIC+self.game_id+'/version.json',timeout=25);r.raise_for_status()
        self.version=r.json()['version']
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}',self.version):raise ValueError('unrecognized_public_version')
        self.settings=self.call('partnerSettings',{'partner':'demo','currency':'EUR','gameId':int(self.game_id),'usePartnerCurrency':True})
        self.auth=self.call('authenticate',{'seq':self.next_seq(),'partner':'demo','gameId':int(self.game_id),'gameVersion':self.version,
            'currency':'EUR','languageCode':'en-us','mode':2,'branding':'default','channel':1,'userAgent':'Mozilla/5.0','token':'demo','currencyMultiplier':1})
        if self.auth.get('name')!='Demo' or self.auth.get('roundStatus') or self.auth.get('roundId') not in ('0',0,None):raise ValueError('not_a_fresh_public_demo')
        if self.auth['accountBalance']['currencyCode']!='EUR':raise ValueError('unexpected_demo_currency')
        self.session=self.auth['sessionUuid']
        self.balance=self.auth['accountBalance']['balance']
        self.bet=str(min(int(b) for b in self.auth['betLevels']))
        if int(self.bet)<=0:raise ValueError('invalid_published_bet')

    def next_seq(self):
        self.seq+=1;return self.seq

    def call(self,endpoint,request):
        if endpoint not in ('partnerSettings','authenticate','bet'):raise ValueError('unsupported_demo_method')
        if endpoint=='authenticate' and (request.get('partner')!='demo' or request.get('mode')!=2):raise ValueError('public_demo_only')
        if endpoint=='partnerSettings' and request.get('partner')!='demo':raise ValueError('public_demo_only')
        step={'endpoint':'/api/play/'+endpoint,'request':redact(request),'started':time.time()};self.trace.append(step)
        # Requests has no retry adapter: an uncertain bet is never resubmitted here.
        response=self.http.post(API+endpoint,json=request,timeout=25)
        step.update(http_status=response.status_code,elapsed_ms=round((time.time()-step['started'])*1000,1))
        response.raise_for_status();data=response.json();step['response']=redact(data)
        if data.get('statusCode')!=0:raise ValueError('provider_error:'+str(data.get('statusCode'))+':'+str(data.get('statusMessage','')))
        return data

    def wager(self,bonus_id=None,base_mode=None):
        bet={'betAmount':self.bet}
        if bonus_id is not None:
            offered={b['bonusGameId'] for b in self.auth.get('bonusGames') or []}
            if bonus_id not in offered:raise ValueError('unpublished_bonus_id')
            bet['buyBonus']=bonus_id
        bet.update(native_extra(self.game_id,bonus_id,base_mode))
        return self.call('bet',{'seq':self.next_seq(),'sessionUuid':self.session,'bets':[bet],'offerId':None,'promotionId':None,'autoplay':False})

    def step(self,round_id,action):
        return self.call('bet',{'seq':self.next_seq(),'sessionUuid':self.session,'roundId':round_id,'continueInstructions':{'action':action}})

    def close(self):self.http.close()
