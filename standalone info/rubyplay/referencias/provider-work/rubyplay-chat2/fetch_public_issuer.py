"""Fetch a public issuer referenced by the leaf AIA. It is NOT made a trust root."""
import hashlib,json,ssl
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from har_probe import ROOT
from catalog_network import durable

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--original-aia-http',action='store_true');args=parser.parse_args()
    # HTTP is the certificate's exact public AIA reference. These untrusted bytes
    # are only an intermediate candidate; RubyPlay HTTPS still requires a full
    # valid chain to the pre-existing Mozilla roots and a matching hostname.
    url=('http' if args.original_aia_http else 'https')+'://cert.ssl.com/SSL.com-TLS-I-RSA-R1.cer'
    folder=ROOT/'private/network';meta=folder/('public-issuer-aia-http.json' if args.original_aia_http else 'public-issuer-download.json');path=folder/'SSL.com-TLS-I-RSA-R1.cer'
    if meta.exists():raise SystemExit('Prior issuer download exists; inspect it rather than retry.')
    durable(meta,{'url':url,'purpose':'leaf AIA issuer discovery; no new trust anchor','state':'intent'})
    ctx=ssl.create_default_context(cafile=str(folder/'certifi-2026.2.25.pem'))
    try:
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),context=ctx,timeout=30) as r:
            data=r.read(100_000);status=r.status
        path.write_bytes(data)
        result={'url':url,'state':'received','status':status,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'tls_validation':not args.original_aia_http,'public_certificate_candidate_only':True,
                'trusted_anchor_added':False,'requires_full_chain_validation':True}
    except Exception as error:result={'url':url,'state':'failed','error_type':type(error).__name__,'error':str(error)[:300]}
    durable(meta,result);print(json.dumps(result))
