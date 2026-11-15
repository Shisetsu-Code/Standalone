"""Official public practice=1/demo=2 transport. No captured sessions."""
import json,re,time
from urllib.parse import quote,urlsplit
import requests,websocket
from playngo_protocol import commands,encode_frame,decode_frames,sanitize_commands

RELEASED='https://released.playngonetwork.com'
SERVER='https://ascflyp.playngonetwork.com/'

class Playngo:
    def __init__(self,game,save):
        self.game=game;self.save=save;self.trace=[];self.http=requests.Session();self.ws=None;self.sid='0';self.packet=1

    def get(self,path,params=None):
        response=self.http.get(RELEASED+path,params=params,timeout=45,allow_redirects=False);response.raise_for_status();return response

    def bootstrap(self):
        gid=self.game['gid']
        if not re.fullmatch('[a-z0-9]+',gid or ''):raise ValueError('unverified_public_gid')
        launch=self.get('/casino/ContainerLauncher',{'pid':2,'gid':gid,'lang':'en_GB','practice':1,'channel':'desktop','demo':2})
        if 'practice' not in launch.text:raise ValueError('unrecognized_demo_launcher')
        info=self.get('/games/getgamebygid/'+gid).json()
        if str(info['gameId'])!=self.game['id']:raise ValueError('catalog_game_id_mismatch')
        match=re.search(r'productGroup:\s*(\d+)',launch.text)
        if not match or match[1]!='2':raise ValueError('unexpected_public_product_group')
        group=2;pre=self.get('/configuration/prelaunchconfiguration',{'gameId':info['gameId'],'language':'en_GB','productGroup':group,'practice':1,'channel':'desktop'}).json()
        if pre.get('Server')!=SERVER:raise ValueError('unverified_demo_server')
        self.authority={'gid':gid,'game_id':self.game['id'],'pid':2,'practice':1,'demo':2,'server':SERVER,'product_group':group}
        ua=quote('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36',safe='')
        response=self.post('103 '+str(10*group-8)+' "en_GB" '+self.game['id']+' "'+ua+'" "'+gid+'" "desktop"')
        session=next((args[0] for code,args in response if code==103 and args),None)
        if not session:raise ValueError('fresh_demo_session_missing')
        self.sid=session
        response=self.post('101 "" "" "" "" "" ""')
        login=next((args for code,args in response if code==101),None)
        if not login or int(login[0])<=0 or login[1]!='DEMO':raise ValueError('practice_login_not_confirmed')
        new_session=next((args[0] for code,args in response if code==103 and args),None)
        if new_session:self.sid=new_session
        self.authority['currency']=login[1]
        self.configuration=self.get('/configuration/v2',{'pid':group,'gameid':self.game['id'],'lang':'en_GB','practice':1,'channel':'desktop','jurisdiction':login[3] if len(login)>3 else 'GB','platform':'megaton','currency':login[1],'_r':str(time.time_ns())}).json()
        self.save(self)
        return response

    def post(self,command):
        body='d='+str(self.packet)+'\r\n'+self.sid+'\r\n'+command+'\r\n';self.packet+=1
        step={'transport':'http','status':'sending','commands':sanitize_commands(commands(command))};self.trace.append(step);self.save(self)
        response=self.http.post(SERVER,data=body.encode(),headers={'Content-Type':'text/plain','Origin':RELEASED},timeout=45,allow_redirects=False)
        step.update(http_status=response.status_code,status='received');response.raise_for_status()
        parsed=commands(response.text);step['responses']=sanitize_commands(parsed);self.save(self);return parsed

    def connect(self):
        self.ws=websocket.create_connection('wss://ascflyp.playngonetwork.com//gamehub',origin=RELEASED,timeout=30)
        self.ws.send(json.dumps({'protocol':'messagepack','version':2})+'\x1e')
        response=self.ws.recv()
        if isinstance(response,bytes):response=response.decode()
        if json.loads(response.rstrip('\x1e'))!={}:raise ValueError('signalr_handshake_not_accepted')

    def send(self,command):
        body='d='+str(self.packet)+'\r\n'+self.sid+'\r\n'+command+'\r\n';self.packet+=1
        step={'transport':'websocket','status':'sending','commands':sanitize_commands(commands(command))};self.trace.append(step);self.save(self)
        self.ws.send_binary(encode_frame([1,{},None,'ProcessPacket',[body],[]]));received=[]
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            frame=self.ws.recv()
            if isinstance(frame,str):raise ValueError('unexpected_text_frame')
            for value in decode_frames(frame):
                if value[0]==6:continue
                if value[0]==7:raise ValueError('native_transport_closed')
                if value[0]==1 and value[3]=='Commands':received.extend(commands(value[4][0]))
            if received:
                step.update(status='received',responses=sanitize_commands(received));self.save(self);return received
        raise TimeoutError('native_reply_not_received')

    def close(self):
        if self.ws:self.ws.close()
        self.http.close()
