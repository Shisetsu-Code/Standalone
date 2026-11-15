import unittest
import requests
from geco_transport import native_geco_session

class NativeTransportTests(unittest.TestCase):
    def test_cross_origin_native_xhr_does_not_send_browser_or_session_cookies(self):
        session=native_geco_session({'origin':'https://affiliate0000001-static2.casinomodule.com','cookie':'private-fixture'})
        session.cookies.set('fixture','not-sent',domain='showcase.evo-games.com',path='/')
        request=requests.Request('GET','https://showcase.evo-games.com/public/rng/dragon/servlet/CasinoGameServlet',headers={'Cookie':'also-not-sent'})
        prepared=session.prepare_request(request)
        self.assertNotIn('Cookie',prepared.headers)
        self.assertEqual(prepared.headers['Origin'],'https://affiliate0000001-static2.casinomodule.com')
        self.assertFalse(session.trust_env)
