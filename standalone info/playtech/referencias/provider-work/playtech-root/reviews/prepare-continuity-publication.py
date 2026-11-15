"""Copy an explicit reviewed allowlist to the existing Git checkout, without deleting files."""
from pathlib import Path
import collections,datetime,hashlib,json,re,shutil,subprocess,sys
R=Path(__file__).resolve().parents[3];T=R/'evidencia-backup-publish'
assert (T/'.git').is_dir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf8'))
files=set()
def add(p):
 p=Path(p)
 assert p.is_file()and p.resolve().is_relative_to(R.resolve())and not p.is_symlink()
 files.add(p.relative_to(R))
def tree(path,extensions):
 for p in (R/path).rglob('*'):
  if p.is_file()and p.suffix in extensions and not any(v in p.parts for v in ['__pycache__','node_modules','.git','private','source-cache','runs','profiles','campaign','candidates','test-temp','.review-test-temp']):add(p)
tree('demo-dashboard/playtech',{'.json','.html'})
tree('demo-dashboard/peterandsons',{'.json','.html'})
tree('demo-dashboard/kagaming',{'.json','.html'})
tree('demo-dashboard/parallel',{'.json','.html'})
tree('demo-dashboard/docs/relay-qa',{'.md'})
add(R/'demo-dashboard/providers.html')
for name in ['parallel_tools/contracts.py','parallel_tools/workspaces.py','parallel_tools/worker_runtime.py','parallel_tools/worker_service.py','parallel_tools/test_contracts.py','parallel_tools/test_workspaces.py','parallel_tools/test_services_local.py','playtech-private-root/publish_reports.py','provider-work/playtech-root/HANDOFF.md','provider-work/playtech-root/CONTINUITY.md','provider-work/playtech-root/live/ngm-throughput-plan.json','provider-work/coordination/SCOPE.md','provider-work/coordination/resume-checkpoint-2026-11-01.json','provider-work/coordination/imports/peterandsons-dashboard.json','provider-work/coordination/kagaming-final-consolidation.json','docs/superpowers/plans/2026-10-31-ngm-family-loader.md','docs/superpowers/plans/2026-10-31-playtech-full-verification.md']:
 add(R/name)
for p in (R/'playtech-private-root/ngm-families').iterdir():
 if p.is_file()and p.suffix in ['.py','.cjs']:add(p)
review_names=['ngm-current-coverage-audit.json','ngm-profile-evidence-reference-audit.json','ngm-registered-offline-audit.json','ngm-audit-throughput-measurement.json','ngm-samz-production-integration-hold.json','ngm-samz-production-host-fixture-fix-v3.json','ngm-sourceonly-epa-native-normal-inventory-candidate.json','ngm-sourceonly-aogmt-work-checkpoint.json','ngm-frtlgsk-native-normal-static-checkpoint.json','ngm-jdlo-source-only-handoff-checkpoint.json','peterandsons-chat4-delivery-root-review.json','audit-peterandsons-chat4-delivery.py','publish-peterandsons-dashboard.py','prepare-continuity-publication.py']
for n in review_names:add(R/'provider-work/playtech-root/reviews'/n)
for n in ['protocol.py','campaign.py','conditional_cases.py','final_audit.py','analyze_hars.py','test_protocol.py','test_conditional.py','test_campaign.py']:add(R/'provider-work/peterandsons-chat4/code'/n)
for n in ['CONTINUITY.md','AGENTS.md']:add(R/'provider-work/peterandsons-chat4'/n)
# Refresh the dependency reference in the derived coverage report, not the registry or history.
coverage=R/'provider-work/playtech-root/reviews/ngm-current-coverage-audit.json';c=read(coverage)
c['registry_offline_audit']['sha256']=sha(R/c['registry_offline_audit']['path'])
coverage.write_text(json.dumps(c,indent=2)+'\n',encoding='utf8')
# The resume checkpoint pins selected original-machine inputs, some intentionally private.
resume=R/'provider-work/coordination/resume-checkpoint-2026-11-01.json';s=read(resume)
for v in s['references']:
 p=R/v['path'];v.update(sha256=sha(p),bytes=p.stat().st_size)
s['created_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();resume.write_text(json.dumps(s,indent=2)+'\n',encoding='utf8')
known=[]
for p in (R/'provider-work/peterandsons-chat4/private/sessions').glob('*/credentials.json'):
 known.extend(str(v).encode()for k,v in read(p).items()if k in ['key','token']and v)
unsafe=re.compile(rb'Bearer\s+[A-Za-z0-9_.-]{24,}|[?&](?:mgckey|token|sessionid|sessionkey|auth)=[A-Za-z0-9_@~.%+-]{12,}',re.I)
frozen=read(T/'docs/relay-qa/netent-frozen-sha256.json')
for name,h in frozen.items():assert sha(T/Path(name))==h,'Frozen NetEnt file changed'
copied=[];unchanged=0
for rel in sorted(files):
 source=R/rel;data=source.read_bytes();assert source.stat().st_size<=90*1024**2
 assert source.suffix.lower()not in ['.har','.log','.sqlite3']and source.name not in ['credentials.json','owner-private.json','initialization-private.json','launch-private.json']
 assert not unsafe.search(data),'Auth-shaped literal in publication candidate: '+str(rel)
 assert not any(secret in data for secret in known),'Known private credential in candidate: '+str(rel)
 target=T/rel;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists()and target.read_bytes()==data:unchanged+=1
 else:target.write_bytes(data);copied.append(rel.as_posix())
 assert target.read_bytes()==data
# Retain the historical top-level prompt as an entry point to the current prompt.
shutil.copyfile(R/'demo-dashboard/docs/relay-qa/PROMPT-CONTINUIDAD.md',T/'PROMPT_CONTINUIDAD.md')
for name,h in frozen.items():assert sha(T/Path(name))==h
metadata=T/'docs/relay-qa';metadata.mkdir(parents=True,exist_ok=True)
stage={'schema':'reviewed-publication-stage/v1','updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository':'Shisetsu-Code/Evidencia','selected_files':len(files),'changed_files':copied,'unchanged_selected_files':unchanged,'known_session_secrets_checked':len(known),'unsafe_auth_literals_found':0,'netent_frozen_files_verified':len(frozen),'new_original_game_outcomes':0,'private_inputs_excluded':True,'scope':'Reviewed dashboards, selected tools, handoff documents and hash references. Not a complete private-runtime backup.'}
(metadata/'publication-stage-2026-11-01.json').write_text(json.dumps(stage,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:stage[k]for k in ['selected_files','unchanged_selected_files','netent_frozen_files_verified','new_original_game_outcomes']},ensure_ascii=True));print('Changed copied files:',len(copied))
