import io,json
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from urllib.request import Request
from all_lucky_variants import VariantGate
import diagnose_all_lucky_redirect as x

class LuckyRedirect(unittest.TestCase):
 def context(self):
  cfg={'identifier':'AllLuckyClover','currency':'FUN','server_id':'demo','lobby_launch_url':'https://demo.bgaming-network.com/lobby/FUN/private-session/launch','api':'https://demo.bgaming-network.com/api/private','csrfTokenHeaderName':'X-CSRF','csrfTokenHeaderValue':'private-csrf'}
  checkpoint={'method':'GET','url':cfg['lobby_launch_url']+'?game=AllLuckyClover5&from=AllLuckyClover','headers':{'Content-Type':'application/json','X-CSRF':'private-csrf'},'body':None,'status':'uncertain_or_rejected','error_type':'ValueError','error':'Selector/API redirected','http_status':None,'response_body':''}
  own={'fresh_demo':True,'game_id':'AllLuckyClover','api':cfg['api'],'csrf_name':'X-CSRF','csrf_value':'private-csrf','last_request':{'command':'init'},'operation':{'status':'received'}}
  return cfg,checkpoint,own
 def test_discarded_body_is_not_labeled_provider_rejection(self):
  cfg,checkpoint,own=self.context();summary=x.classify_checkpoint(checkpoint)
  self.assertEqual(summary['classification'],'local_redirect_guard_body_not_read')
  self.assertFalse(summary['provider_rejection_proved']);self.assertNotIn('private',json.dumps(summary))
 def test_one_official_redirected_get_retains_body_and_headers_privately(self):
  cfg,checkpoint,own=self.context();private=[];calls=[]
  body=json.dumps({'identifier':'AllLuckyClover5','currency':'FUN','server_id':'demo','api':'https://demo.bgaming-network.com/api/private-fresh','csrfTokenHeaderValue':'private-next'}).encode()
  class Response:
   url='https://demo.bgaming-network.com/lobby/result?game=AllLuckyClover5&token=REDACTED';status=200
   headers={'Content-Type':'application/json','Set-Cookie':'private-cookie'}
   def read(self):return body
   def __enter__(self):return self
   def __exit__(self,*args):pass
  def factory(handler,opener):
   def open(req,timeout):calls.append(req);return Response()
   return SimpleNamespace(open=open)
  with tempfile.TemporaryDirectory() as root:
   gate=VariantGate(root,last_launch_epoch=0,clock=lambda:1000)
   with gate:result=x.observe_once(checkpoint,cfg,own,SimpleNamespace(handlers=[]),gate=gate,private_checkpoint=lambda stage,data:private.append((stage,data)),opener_factory=factory)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0].get_method(),'GET');self.assertIsNone(calls[0].data)
  self.assertEqual(result.private_body,body);self.assertEqual(result.parsed_options['identifier'],'AllLuckyClover5')
  public=json.dumps(result.public_summary());self.assertNotIn('private-csrf',public);self.assertNotIn('private-cookie',public);self.assertNotIn('private-redirect',public);self.assertNotIn('private-fresh',public)
  final=private[-1][1];self.assertEqual(final['body_base64'],__import__('base64').b64encode(body).decode());self.assertIn(('Set-Cookie','private-cookie'),final['headers'])
 def test_external_redirect_is_rejected_before_follow(self):
  records=[];handler=x.OfficialRedirectHandler(lambda stage,item:records.append((stage,item)))
  req=Request('https://demo.bgaming-network.com/lobby/start',headers={'X-CSRF':'private'})
  with self.assertRaises(ValueError):handler.redirect_request(req,io.BytesIO(b'redirect'),302,'Found',{'Location':'https://evil.example/'},'https://evil.example/')
  self.assertEqual(records[-1][0],'blocked_redirect')
 def test_html_bootstrap_is_classified_without_running_javascript(self):
  raw=b'<script>window.__OPTIONS__ = {"identifier":"AllLuckyClover5","currency":"FUN","api":"https://demo.bgaming-network.com/api/private"}; throw new Error("not executed");</script>'
  kind,options=x.parse_body(raw);self.assertEqual(kind,'bootstrap_options_html');self.assertEqual(options['identifier'],'AllLuckyClover5')
 def test_wrong_context_or_post_never_opens_transport(self):
  cfg,checkpoint,own=self.context();checkpoint['method']='POST'
  with tempfile.TemporaryDirectory() as root:
   gate=VariantGate(root,last_launch_epoch=0,clock=lambda:1000)
   with gate:
    with self.assertRaises(ValueError):x.observe_once(checkpoint,cfg,own,SimpleNamespace(handlers=[]),gate=gate,private_checkpoint=lambda *a:None,opener_factory=lambda *a:self.fail('Must not open'))
 def test_same_origin_redirect_preserves_native_bootstrap_headers_and_raw_hop(self):
  records=[];handler=x.OfficialRedirectHandler(lambda stage,item:records.append((stage,item)))
  req=Request('https://demo.bgaming-network.com/lobby/start',headers={'Content-Type':'application/json','X-CSRF':'private-csrf'})
  redirected=handler.redirect_request(req,io.BytesIO(b'raw redirect body'),302,'Found',{'Location':'/lobby/final','Set-Cookie':'private-hop-cookie'},'https://demo.bgaming-network.com/lobby/final')
  self.assertEqual(redirected.get_header('X-csrf'),'private-csrf');self.assertEqual(redirected.get_method(),'GET')
  self.assertEqual(__import__('base64').b64decode(records[0][1]['body_base64']),b'raw redirect body')
 def test_cross_origin_official_redirect_does_not_forward_csrf(self):
  handler=x.OfficialRedirectHandler(lambda *args:None)
  req=Request('https://demo.bgaming-network.com/lobby/start',headers={'X-CSRF':'private-csrf','User-Agent':'Mozilla/5.0'})
  redirected=handler.redirect_request(req,io.BytesIO(b''),302,'Found',{'Location':'https://cdn.bgaming-network.com/final'},'https://cdn.bgaming-network.com/final')
  self.assertIsNone(redirected.get_header('X-csrf'));self.assertTrue(handler.records[0]['origin_changed'])
