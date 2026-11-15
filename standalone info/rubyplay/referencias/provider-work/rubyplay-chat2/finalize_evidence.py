"""Create an allowlisted, sanitized delivery manifest; performs no network I/O."""
from datetime import datetime,timezone
import hashlib,json
from har_probe import ROOT
from catalog_network import durable
from verify_catalog import audit

if __name__=='__main__':
    checked=audit()
    checked['checked_at']=datetime.now(timezone.utc).isoformat()
    checked['regression_command']='.venv/Scripts/python.exe -B -X utf8 -m unittest -q test_catalog'
    checked['regression_results']='See verification-run.txt for the actual offline test count and outcome.'
    durable(ROOT/'results/verification.json',checked)
    files=[]
    for pattern in ('catalogs/*.json','catalogs/*.html','sources/*.json','results/provider-report.json','results/verification.json','results/monitoring.json',
                    'results/scope-authorization.json','results/link-capture-checkpoint.json','results/client-preparation.json',
                    'results/live-summary.json','results/first-normal.json','results/first-purchase.json','results/game-processing-queue.json',
                    'results/rp_*-preparation.json','results/rp_*-binding.json','results/rp_*-normal.json',
                    'results/rp_*-purchase-*.json','results/rp_*-root-state.json',
                    'results/batch-progress.json','results/batch-pending.json','native_contracts.json',
                    'results/coverage-final.json',
                    'results/batch-history/*.json',
                    '*.py','*.cjs','*.ps1','*.md','.gitignore','verification-run.txt'):
        for path in ROOT.glob(pattern):
            files.append({'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    durable(ROOT/'results/evidence-manifest.json',{'provider':'rubyplay','created_at':checked['checked_at'],
         'scope':'Sanitized catalogue metadata and local source code; private files and raw HAR excluded.',
         'self_hash_excluded':True,'files':sorted(files,key=lambda r:r['path'])})
    print(json.dumps(audit(manifest=True)))
