"""Sequential authorized Ruby accumulation and native purchases; stops on errors."""
import json,subprocess,sys,os
from har_probe import ROOT
from catalog_network import durable
from worker_lock import worker_lock

def main():
    progress={'pid':os.getpid(),'state':'running','games':{'rp_65':'purchase_verified'}}
    path=ROOT/'results/ruby-purchases-progress.json'
    for game in ('rp_57','rp_37','rp_26','rp_29'):
        progress.update(current_game=game);progress['games'][game]='accumulating';durable(path,progress)
        for command in (['node','--expose-internals','validate_next_init.cjs',game],
                        [sys.executable,'-B','run_next_normal.py',game,'--ruby-probe','--ruby-buy']):
            run=subprocess.run(command,cwd=ROOT)
            if run.returncode:
                progress['state']='stopped_needs_review';durable(path,progress);return
        result=ROOT/('results/'+game+'-ruby-purchase.json')
        if not result.exists() or not json.loads(result.read_text(encoding='utf8'))['finished']:
            progress['state']='stopped_threshold_not_reached';durable(path,progress);return
        progress['games'][game]='purchase_verified';durable(path,progress)
    progress.update(state='complete',current_game=None);durable(path,progress)

if __name__=='__main__':
    with worker_lock('ruby-cases'):main()
