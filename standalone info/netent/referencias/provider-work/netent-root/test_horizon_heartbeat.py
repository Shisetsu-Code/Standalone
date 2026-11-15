import json,unittest
from horizon_heartbeat import Heartbeat

class HeartbeatTests(unittest.TestCase):
    def test_native_ping_is_periodic_and_never_a_slot_call(self):
        sent=[];beat=Heartbeat()
        beat.tick(sent.append,now=10);beat.tick(sent.append,now=12);beat.tick(sent.append,now=15)
        self.assertEqual(len(sent),2)
        for raw in sent:
            p=json.loads(raw);self.assertEqual(p['recipient'],'ping-pong')
            self.assertEqual(p['payload']['type'],'metrics.ping')
            self.assertNotIn('details',p['payload'])
