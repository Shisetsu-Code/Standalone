"""Serial adaptive demo-launch spacing; honors server cooldowns, never retries play."""
import json,time,msvcrt
from email.utils import parsedate_to_datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent
POLICY=ROOT/'rate-policy.json'


def retry_after_seconds(value,now=None):
    now=time.time() if now is None else now
    try:return max(0,int(value))
    except (ValueError,TypeError):
        try:return max(0,int(parsedate_to_datetime(value).timestamp()-now))
        except (ValueError,TypeError,OverflowError,AttributeError):return 0


def feedback(policy,outcome,*,retry_after=0,now=None):
    now=time.time() if now is None else now
    result=dict(policy);interval=result.get('interval',20)
    if outcome=='success':
        count=result.get('successes',0)+1
        if count>=5:interval=max(result.get('floor',10),interval-5);count=0
        result.update(interval=interval,successes=count)
    elif outcome in ['rate_limited','blocked','transient']:
        interval=min(300,max(20,interval*2))
        result.update(interval=interval,successes=0,cooldown_until=now+max(interval,retry_after or 0))
    result.update(last_outcome=outcome,updated_at=now)
    return result


def load_policy():
    return json.loads(POLICY.read_text(encoding='utf8')) if POLICY.exists() else {'interval':20,'floor':10,'successes':0}


def feedback_file(outcome,retry_after=0):
    value=feedback(load_policy(),outcome,retry_after=retry_after)
    temp=POLICY.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf8');temp.replace(POLICY)
    return value


class GameStartGate:
    def __init__(self,path):self.path=Path(path)

    def start(self,slug):
        with self.path.with_suffix('.lock').open('a+b') as lock:
            lock.write(b'0');lock.flush();lock.seek(0)
            while True:
                try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:time.sleep(1)
            try:self._start_locked(slug)
            finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

    def _start_locked(self,slug):
        state=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else {'starts':[]}
        last=state['starts'][-1]['epoch'] if state['starts'] else 0
        announced=False
        while True:
            policy=load_policy();spacing=policy.get('interval',20)
            target=max(last+spacing,policy.get('cooldown_until',0));remaining=target-time.time()
            if remaining<=0:break
            if not announced:print(json.dumps({'event':'adaptive_launch_wait','game':slug,'seconds':round(remaining,2),'interval':spacing}),flush=True);announced=True
            time.sleep(min(2,remaining))
        state['starts'].append({'slug':slug,'epoch':time.time(),'required_seconds':spacing})
        state['minimum_seconds']=spacing;state['policy']='adaptive_serial'
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2),encoding='utf8');temp.replace(self.path)
