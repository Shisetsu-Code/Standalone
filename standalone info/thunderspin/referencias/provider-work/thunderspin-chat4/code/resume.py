"""Resume only a confirmed native continuation; never a paid entry."""
import json,pathlib,sys,msvcrt
from campaign import ROOT,Campaign
def main():
 p=(ROOT/sys.argv[1]).resolve()
 if not p.is_relative_to(ROOT/'private/rounds'):raise ValueError('case_out_of_scope')
 lock=open(ROOT/'private/campaign.lock','r+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 try:
  c=json.loads(p.read_text());cfg=json.loads((ROOT/'private/sessions'/('own-'+c['session_fingerprint'])/'credentials.json').read_text());init_path=pathlib.Path(c['source_init_reference']);init=json.loads(init_path.read_text());q=c['journal'][0]['request']
  Campaign().run_case(cfg,c['session_fingerprint'],init,init_path,c['mode'],c['expected_cost_cents'],q['denomination'],q['betlevel'],q.get('lines',0),resume=True)
 finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':main()
