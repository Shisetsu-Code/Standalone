"""Observed native ping-pong / metrics.ping heartbeat, independent of wagers."""
import json,time,uuid

class Heartbeat:
    def __init__(self):self.next_at=0
    def tick(self,send,*,now=None):
        now=time.time() if now is None else now
        if now<self.next_at:return
        packet={'recipient':'ping-pong','payload':{'id':uuid.uuid4().hex[:10],
                'type':'metrics.ping','args':{'t':int(now*1000)}}}
        send(json.dumps(packet));self.next_at=now+5
