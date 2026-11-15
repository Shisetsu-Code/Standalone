"""Validate RubyPlay using the existing certifi CA bundle; no HTTP, no TLS bypass."""
import hashlib,json,socket,ssl
from pathlib import Path
from datetime import datetime,timezone
from catalog_network import durable
from har_probe import ROOT

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--with-issuer',action='store_true');args=parser.parse_args()
    source=Path(r'C:/Users/Shisetsu/AppData/Local/Programs/Python/Python311/Lib/site-packages/certifi/cacert.pem')
    data=source.read_bytes();target=ROOT/'private/network/certifi-2026.2.25.pem'
    if target.exists() and target.read_bytes()!=data:raise ValueError('pinned_CA_bundle_changed')
    target.write_bytes(data)
    issuer=ROOT/'private/network/SSL.com-TLS-I-RSA-R1.cer'
    if args.with_issuer:
        data+=ssl.DER_cert_to_PEM_cert(issuer.read_bytes()).encode('ascii')
        target=ROOT/'private/network/certifi-2026.2.25-with-issuer.pem';target.write_bytes(data)
    ctx=ssl.create_default_context(cafile=str(target))
    assert ctx.check_hostname and ctx.verify_mode==ssl.CERT_REQUIRED
    assert not (ctx.verify_flags & getattr(ssl,'VERIFY_X509_PARTIAL_CHAIN',0))
    result={'host':'rubyplay.com','checked_at':datetime.now(timezone.utc).isoformat(),
            'ca_source':'Existing installed certifi 2026.2.25 Mozilla CA bundle',
            'ca_file':target.relative_to(ROOT).as_posix(),'ca_sha256':hashlib.sha256(data).hexdigest(),
            'hostname_validation':True,'certificate_validation':'CERT_REQUIRED','http_requests_sent':0}
    try:
        with socket.create_connection(('rubyplay.com',443),timeout=20) as tcp:
            with ctx.wrap_socket(tcp,server_hostname='rubyplay.com') as connection:
                cert=connection.getpeercert();result.update({'passed':True,'tls_protocol':connection.version(),
                    'leaf_der_sha256':hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest(),
                    'leaf_subject':cert.get('subject'),'leaf_issuer':cert.get('issuer'),'valid_until':cert.get('notAfter')})
                if args.with_issuer:
                    try:ssl.match_hostname(cert,'wrong-host.invalid')
                    except ssl.CertificateError:result['wrong_hostname_rejected']=True
                    else:raise ValueError('hostname_negative_control_failed')
        if args.with_issuer:
            negative=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            negative.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(issuer.read_bytes()))
            assert not (negative.verify_flags & getattr(ssl,'VERIFY_X509_PARTIAL_CHAIN',0))
            try:
                with socket.create_connection(('rubyplay.com',443),timeout=20) as tcp:
                    with negative.wrap_socket(tcp,server_hostname='rubyplay.com'):pass
            except ssl.SSLCertVerificationError:result['intermediate_alone_rejected_without_trusted_roots']=True
            else:raise ValueError('intermediate_must_not_become_trust_anchor')
            result['added_intermediate_sha256']=hashlib.sha256(issuer.read_bytes()).hexdigest()
            result['added_trust_roots']=0
    except Exception as error:result.update({'passed':False,'error_type':type(error).__name__,'error':str(error)[:300]})
    durable(ROOT/('private/network/rubyplay-tls-chain-fixed.json' if args.with_issuer else 'private/network/rubyplay-tls-resolution.json'),result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
