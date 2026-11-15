"""Native Endorphina public-demo JSON WebSocket transport.

Launches fresh guest sessions from official catalog links. No HAR sessions are
reused. Trace files contain protocol messages, never session URLs or signatures.
"""
import json
import re
import time
from decimal import Decimal
from urllib.parse import parse_qs, quote, urlencode, urlsplit
import requests
import websocket

METHODS = {'GET_PAYTABLE_INFO', 'GET_BALANCE', 'GET_LAST_GAME', 'GET_DYNAMIC_HELP_INFO',
           'START_GAME', 'START_FEATURE', 'STEP_FEATURE', 'END_FEATURE', 'END_GAME'}


def matches_reply(message, request_id):
    return message.get('requestId') is not None and str(message['requestId']) == str(request_id)


def native_bet(paytable, history):
    p = dict(history['betting_param'])
    if history['status'] != 'FINISHED':
        raise ValueError('fresh_session_has_unfinished_round')
    if (p['bet_per_line'] not in paytable['bets_set'] or p['num_of_lines'] not in paytable['lines_set']
            or Decimal(p['denom']) not in [Decimal(x) for x in paytable['denoms_set']]):
        raise ValueError('unpublished_initial_bet')
    p.update(extra_bet=0, bonusId='')
    p.pop('buyInId', None)
    return p


class Endorphina:
    def __init__(self, play_url):
        u = urlsplit(play_url)
        if u.scheme != 'https' or u.hostname != 'endorphina.com' or not re.fullmatch(r'/(?:es/juegos|games)/[a-z0-9-]+/play', u.path):
            raise ValueError('not_an_official_public_demo')
        self.trace, self.number, self.ws = [], 0, None
        self.http = requests.Session()
        self.http.headers['User-Agent'] = 'Mozilla/5.0'
        r = self.http.get(play_url, timeout=25)
        r.raise_for_status()
        match = re.search(r"window.location.href\s*=\s*'([^']+)'", r.text)
        if not match or urlsplit(match[1]).hostname != 'edemo.endorphina.com':
            raise ValueError('unrecognized_official_launcher')
        r = self.http.get(match[1], timeout=25)
        r.raise_for_status()
        if urlsplit(r.url).hostname != 'demo.endorphina.network':
            raise ValueError('unexpected_demo_host')
        self.asset_base='https://demo.endorphina.network'+urlsplit(r.url).path.rsplit('/',1)[0]
        q = parse_qs(urlsplit(r.url).query)
        launch_url = q['launch'][0]
        if launch_url != 'https://demo.endorphina.network/organic/websocket/launch':
            raise ValueError('unexpected_launch_endpoint')
        info = quote('UA=Mozilla/5.0&L=en-US&V=1280x720x1&R=1280x720&TZ=GMT-0300&LS=["en-US"]&OS=Win 10.0&ARCH=intel&AR=1&DP=12', safe='')
        r = self.http.post(launch_url, data={'session':q['session'][0], 'sign':q['sign'][0], 'info':info, 'mobile':'false'}, timeout=25)
        r.raise_for_status()
        launch = r.json()
        endpoint = urlsplit(launch['endpoint'])
        if endpoint.scheme != 'wss' or endpoint.hostname != 'dyndemo.endorphina.network' or not re.fullmatch('/organic/websocket/endpoint/[0-9]+', endpoint.path):
            raise ValueError('unexpected_websocket_endpoint')
        self.game, self.name = launch['game'], launch['gameName']
        self.currency = launch['currency']
        ws_url = launch['endpoint'] + '?' + urlencode({k:launch[k] for k in ('session','sign')})
        self.http.get(ws_url.replace('wss:', 'https:', 1), timeout=20).raise_for_status()
        self.ws = websocket.create_connection(ws_url, timeout=15, subprotocols=['json'], origin='https://demo.endorphina.network',
            cookie='; '.join(k+'='+v for k,v in self.http.cookies.get_dict().items()))
        self.connection = {'url':ws_url,'cookies':self.http.cookies.get_dict(),'game':self.game,'name':self.name,'currency':self.currency}
        self.paytable = self.call('GET_PAYTABLE_INFO')
        self.balance = self.call('GET_BALANCE')
        self.history = self.call('GET_LAST_GAME')
        # Public demo funding can arrive shortly after its socket opens.
        for _ in range(6):
            if Decimal(self.balance['balance'])>0:break
            time.sleep(0.4)
            self.balance=self.call('GET_BALANCE')
        self.parameters = native_bet(self.paytable, self.history)

    @classmethod
    def resume(cls, connection):
        self=cls.__new__(cls)
        u=urlsplit(connection['url'])
        if u.scheme!='wss' or u.hostname!='dyndemo.endorphina.network':
            raise ValueError('unexpected_resume_host')
        self.trace,self.number=[],0
        self.http=requests.Session()
        self.http.cookies.update(connection['cookies'])
        self.connection=connection
        self.game,self.name,self.currency=(connection[k] for k in ('game','name','currency'))
        self.http.get(connection['url'].replace('wss:','https:',1),timeout=20).raise_for_status()
        self.ws=websocket.create_connection(connection['url'],timeout=15,subprotocols=['json'],origin='https://demo.endorphina.network',
            cookie='; '.join(k+'='+v for k,v in self.http.cookies.get_dict().items()))
        self.paytable=self.call('GET_PAYTABLE_INFO')
        self.balance=self.call('GET_BALANCE')
        self.history=self.call('GET_LAST_GAME')
        self.parameters=dict(self.history['betting_param'])
        return self

    def call(self, method, payload=None):
        if method not in METHODS:
            raise ValueError('unrecognized_native_method')
        self.number += 1
        if method == 'START_FEATURE':
            payload = ['logic.api.gamelogic.FeatureID', payload]
        request = {'@type':'MethodInvocation', 'requestId':self.number, 'method':method, 'payload':payload}
        step = {'request':request, 'responses':[], 'started':time.time()}
        self.trace.append(step)
        self.ws.send(json.dumps(request))
        for _ in range(100):
            message = json.loads(self.ws.recv())
            step['responses'].append(message)
            if matches_reply(message, self.number):
                step['elapsed_ms'] = round((time.time()-step['started'])*1000, 1)
                result = message.get('payload')
                if isinstance(result, dict) and result.get('@type') == 'InvocationError':
                    raise ValueError('provider_error:' + str(result.get('code')))
                return result
        raise ValueError('matching_response_missing')

    def close(self):
        if self.ws:
            self.ws.close(timeout=2)
        self.http.close()
