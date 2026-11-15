"""Mirror the legacy SDK's cross-origin httpGet without useCredentials."""
import requests
from requests.adapters import HTTPAdapter

class NativeGecoSession(requests.Session):
    def prepare_request(self,request):
        prepared=super().prepare_request(request)
        prepared.headers.pop('Cookie',None)
        return prepared

def native_geco_session(headers=None):
    session=NativeGecoSession();session.trust_env=False
    session.proxies={'http':'http://127.0.0.1:8793','https':'http://127.0.0.1:8793'}
    session.mount('https://',HTTPAdapter(max_retries=0))
    session.headers.update({k:v for k,v in (headers or {}).items() if k.lower() in ['origin','referer','user-agent']})
    return session
