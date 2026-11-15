import copy,json,unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from build_catalog import source_cards
from verify_catalog import validate_gate,validate_complete_source,ROOT
from catalog_network import verified_catalog_context
from complete_links import public_launcher
from demo_transport import native_read

class ScopeTests(unittest.TestCase):
    def test_older_native_session_without_ruby_methods_initializes_offline(self):
        import subprocess
        run=subprocess.run(['node','--expose-internals','validate_next_init.cjs','rp_67'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr[-500:])

    def test_native_choice_bounds_resets_and_select_input_contract(self):
        import subprocess
        run=subprocess.run(['node','test_native_choices.cjs'],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertIn('10 native choice assertions passed',run.stdout)

    def test_related_games_do_not_inflate_provider_catalogue(self):
        html='<div id="top_games_filter"><a class="slotPageOverlay-link" href="/es/slots/A">A</a></div><div id="top_games_filter"><a class="slotPageOverlay-link" href="/es/slots/Unrelated">Unrelated</a></div>'
        self.assertEqual([r['title'] for r in source_cards(html,'slotcatalog')],['A'])

    def test_upcoming_placeholder_does_not_become_fake_game_slug(self):
        html='<h3 class="brxe-gvgnos"><a href="https://rubyplay.com/reel-winners/">Upcoming</a></h3>'
        row=source_cards(html,'rubyplay')[0]
        self.assertFalse(row['detail_link_resolved'])
        self.assertTrue(row['source_key'].startswith('listing-title:'))

    def test_missing_source_prevents_completion_claim(self):
        report=json.loads((ROOT/'results/provider-report.json').read_text(encoding='utf8'))
        altered=copy.deepcopy(report);altered['catalogue']['hybrid_catalogue_complete']=True
        with self.assertRaisesRegex(ValueError,'incomplete_source'):validate_gate(altered)

    def test_closed_gate_rejects_new_rounds(self):
        report=json.loads((ROOT/'results/provider-report.json').read_text(encoding='utf8'))
        report['catalogue']['gameplay_gate_open']=False
        report['new_gameplay_requests_sent']=1
        with self.assertRaisesRegex(ValueError,'gameplay_before'):validate_gate(report)

    def test_tls_repair_cannot_override_http_403(self):
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as folder:
            root=Path(folder);p=root/'private/network';p.mkdir(parents=True)
            (p/'rubyplay.com.blocked.json').write_text(json.dumps({'status':403}),encoding='utf8')
            with patch('catalog_network.ROOT',root):
                with self.assertRaisesRegex(RuntimeError,'source_block_retained'):verified_catalog_context('rubyplay.com')

    def test_tls_repair_requires_negative_controls(self):
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as folder:
            root=Path(folder);p=root/'private/network';p.mkdir(parents=True)
            (p/'rubyplay.com.blocked.json').write_text(json.dumps({'block_type':'tls_identity_validation_failed'}),encoding='utf8')
            (p/'rubyplay-tls-chain-fixed.json').write_text(json.dumps({'ca_file':'private/network/example.pem','passed':True,'hostname_validation':True,'added_trust_roots':0}),encoding='utf8')
            with patch('catalog_network.ROOT',root):
                with self.assertRaisesRegex(RuntimeError,'TLS_correction_not_verified'):verified_catalog_context('rubyplay.com')

    def test_complete_source_requires_final_page_and_contiguous_range(self):
        source={'source':'rubyplay','complete':True,'declared_pages':2,'declared_catalogue_total':2,'termination_verified':True}
        pages=[{'source':'rubyplay','page':1,'range':[1,1],'cards':[{'source_key':'a'}]}]
        with self.assertRaisesRegex(ValueError,'missing_page'):validate_complete_source(source,pages)
        pages.append({'source':'rubyplay','page':2,'range':[3,3],'cards':[{'source_key':'b'}]})
        with self.assertRaisesRegex(ValueError,'range_gap'):validate_complete_source(source,pages)
        pages[1]['range']=[2,2]
        validate_complete_source(source,pages)

    def test_raw_currency_query_is_not_corrupted_as_html_entity(self):
        url='https://prrpeu3.com/launcher?gamename=rp_222&operator=rubyplay.com&server_url=https://srv.prrpeu3.com&currency=EUR&mode=fun'
        self.assertEqual(public_launcher(url),url)
        self.assertEqual(public_launcher(url.replace('&','&amp;')),url)
        self.assertIsNone(public_launcher(url.replace('srv.prrpeu3.com','srv.prrpeu3.com.invalid')))

    def test_setup_transport_cannot_send_round_without_native_plan(self):
        with self.assertRaisesRegex(ValueError,'setup_transport_only_accepts_init'):
            native_read('https://srv.prrpeu3.com/gameserver/demo',ROOT/'tests-temp','forbidden',{'srv.prrpeu3.com'},{'action':'spin'})

    def test_existing_intent_prevents_replay_before_network(self):
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as folder:
            target=Path(folder);(target/'already.journal.json').write_text('{"state":"intent_before_send"}')
            with self.assertRaisesRegex(RuntimeError,'request_already_journaled_no_replay'):
                native_read('https://srv.prrpeu3.com/init-session/demo',target,'already',{'srv.prrpeu3.com'})

    def test_first_native_roots_close_and_reconcile_every_response(self):
        import hashlib
        folder=ROOT/'private/live/rp_222-preparation'
        for mode in ('normal','purchase'):
            result=json.loads((ROOT/f'results/first-{mode}.json').read_text())
            self.assertTrue(result['finished']);self.assertEqual(result['steps'][-1]['next_action'],1)
            previous=result['root_balance']
            for step in result['steps']:
                self.assertEqual(step['before_balance'],previous)
                self.assertEqual(previous-step['cost']+step['paid_win'],step['server_balance'])
                self.assertTrue(step['wallet_matches'])
                journal=json.loads((folder/(step['key']+'.journal.json')).read_text())
                self.assertEqual(journal['status'],200)
                self.assertEqual(journal['sha256'],hashlib.sha256((folder/(step['key']+'.body.private')).read_bytes()).hexdigest())
                previous=step['server_balance']
            self.assertEqual(result['final_balance'],previous)

    def test_semantic_bundle_loader_uses_each_games_own_math_and_rejects_rng(self):
        import subprocess
        script="const {load}=require('./native_bundle.cjs');let results=[];for(let [game,math]of [['rp_222',2025093096],['rp_236',2026032096],['rp_214',20251226]]){let b=load('private/live/'+game+'-preparation/game-js.body.private');if(b.math!==math||b.protocol!==2)throw Error('version_mismatch');let rejected=false;try{b.run('Math.random()')}catch{rejected=true}if(!rejected)throw Error('random_fallback_enabled');if(game==='rp_214'){let alias=b.aliases['com.gongxigames.math.jmaniav6.engine.JManiaV6RespinFeature2Engine'];if(b.run('typeof '+alias+'.Coordinate')!=='function')throw Error('nested_coordinate_missing')}results.push(game)}console.log(JSON.stringify(results))"
        run=subprocess.run(['node','--expose-internals','-e',script],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(run.stdout),['rp_222','rp_236','rp_214'])

    def test_chili_purchase_replays_offline_without_alias_collision(self):
        import subprocess
        run=subprocess.run(['node','--expose-internals','plan_next_normal.cjs','rp_214','--all'],cwd=ROOT,capture_output=True,text=True,check=True)
        result=json.loads(run.stdout)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['modes'],2)
        purchase=json.loads((ROOT/'results/rp_214-purchase-001.json').read_text(encoding='utf8'))
        self.assertTrue(purchase['finished']);self.assertEqual(purchase['steps'][0]['cost'],500)
        self.assertTrue(all(s['expected_balance']==s['server_balance'] for s in purchase['steps']))

    def test_second_native_normal_wallet_and_response_hash(self):
        import hashlib
        r=json.loads((ROOT/'results/rp_236-normal.json').read_text(encoding='utf8'))
        self.assertTrue(r['finished']);previous=r['root_balance']
        for s in r['steps']:
            self.assertEqual(s['before_balance'],previous)
            self.assertEqual(previous-s['cost']+s['paid_win'],s['server_balance'])
            folder=ROOT/'private/live/rp_236-preparation'
            meta=json.loads((folder/(s['key']+'.journal.json')).read_text(encoding='utf8'))
            self.assertEqual(meta['sha256'],hashlib.sha256((folder/(s['key']+'.body.private')).read_bytes()).hexdigest())
            previous=s['server_balance']
        self.assertEqual(r['steps'][-1]['next_action'],1)
        self.assertEqual(r['final_balance'],previous)

    def test_all_native_case_receipts_close_and_reconcile(self):
        import hashlib
        paths=list((ROOT/'results').glob('rp_*-normal.json'))+list((ROOT/'results').glob('rp_*-purchase-*.json'))
        self.assertGreaterEqual(len(paths),9)
        for path in paths:
            r=json.loads(path.read_text(encoding='utf8'));self.assertTrue(r['finished'])
            previous=r['root_balance'];folder=ROOT/('private/live/'+r['game']+'-preparation')
            for s in r['steps']:
                self.assertEqual(s['before_balance'],previous)
                self.assertEqual(previous-s['cost']+s['paid_win'],s['server_balance'])
                meta=json.loads((folder/(s['key']+'.journal.json')).read_text(encoding='utf8'))
                self.assertEqual(meta['status'],200)
                self.assertEqual(meta['sha256'],hashlib.sha256((folder/(s['key']+'.body.private')).read_bytes()).hexdigest())
                previous=s['server_balance']
            self.assertEqual(r['steps'][-1]['next_action'],1);self.assertEqual(r['final_balance'],previous)

    def test_new_families_replay_offline_without_resending(self):
        import subprocess
        for game in ('rp_220','rp_216','rp_211'):
            folder=ROOT/('private/live/'+game+'-preparation')
            before={p.name:p.read_bytes() for p in folder.glob('*.journal.json')}
            run=subprocess.run(['node','--expose-internals','plan_next_normal.cjs',game,'--all'],cwd=ROOT,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(run.stdout)['state'],'complete')
            self.assertEqual(before,{p.name:p.read_bytes() for p in folder.glob('*.journal.json')})

    def test_namespace_math_helpers_and_stream_replay_close_without_sends(self):
        import subprocess
        for game,modes in (('rp_200',2),('rp_228',1)):
            folder=ROOT/('private/live/'+game+'-preparation')
            before={p.name:p.read_bytes() for p in folder.glob('*.journal.json')}
            run=subprocess.run(['node','--expose-internals','plan_next_normal.cjs',game,'--all','--stream'],input='',cwd=ROOT,capture_output=True,text=True,check=True,timeout=30)
            result=json.loads(run.stdout)
            self.assertEqual(result['state'],'complete');self.assertEqual(result['modes'],modes)
            self.assertEqual(before,{p.name:p.read_bytes() for p in folder.glob('*.journal.json')})

if __name__=='__main__':unittest.main()
