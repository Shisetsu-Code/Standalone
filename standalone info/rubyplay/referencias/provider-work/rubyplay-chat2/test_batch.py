import json,unittest,importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from har_probe import ROOT

class BatchSchedulingTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('batch_runner'),'Batch scheduler is missing')
        import batch_runner
        return batch_runner

    def test_completed_games_are_skipped_and_same_revision_failures_stay_pending(self):
        api=self.api()
        games=[{'native_identity':'rp_1','public_demo_url':'a'},{'native_identity':'rp_2','public_demo_url':'b'},
               {'native_identity':'rp_3','public_demo_url':'c'},{'native_identity':None}]
        states={'rp_1':{'state':'closed'},'rp_2':{'state':'needs_contract','revision':'v1'}}
        self.assertEqual([g['native_identity'] for g in api.select_candidates(games,states,'v1')],['rp_3'])
        self.assertEqual([g['native_identity'] for g in api.select_candidates(games,states,'v2')],['rp_2','rp_3'])

    def test_uncertain_financial_receipt_blocks_all_games_before_selection(self):
        api=self.api()
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as temp:
            root=Path(temp);folder=root/'private/live/rp_1-preparation';folder.mkdir(parents=True)
            (folder/'normal-0001.journal.json').write_text(json.dumps({'financial_action':True,'state':'intent_before_send'}))
            with self.assertRaisesRegex(RuntimeError,'uncertain_financial_request'):api.check_financial_receipts(root)

    def test_persisted_http_block_stops_batch_without_new_attempts(self):
        api=self.api()
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as temp:
            root=Path(temp);network=root/'private/network';network.mkdir(parents=True)
            (network/'srv.prrpeu3.com.blocked.json').write_text('{"status":429}')
            with self.assertRaisesRegex(RuntimeError,'provider_access_block_retained'):api.check_game_hosts(root)

    def test_active_root_is_scheduled_before_unstarted_games(self):
        api=self.api()
        games=[{'native_identity':'rp_1','public_demo_url':'a'},{'native_identity':'rp_2','public_demo_url':'b'}]
        self.assertEqual([g['native_identity'] for g in api.select_candidates(games,{'rp_2':{'state':'active'}},'v')],['rp_2','rp_1'])

    def test_worker_lock_prevents_concurrent_batch(self):
        from worker_lock import worker_lock
        with worker_lock('test-batch-duplicate'):
            with self.assertRaisesRegex(RuntimeError,'worker_already_running'):
                with worker_lock('test-batch-duplicate'):pass

    def test_request_claim_without_journal_is_never_replayed(self):
        api=self.api()
        base=ROOT/'tests-temp';base.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=base) as temp:
            root=Path(temp);folder=root/'private/live/rp_1-preparation';folder.mkdir(parents=True)
            (folder/'normal-0001.claim').write_text('{"financial_action":true}')
            with self.assertRaisesRegex(RuntimeError,'uncertain_financial_request_claim_without_journal'):api.check_financial_receipts(root)

    def test_contract_change_resumes_only_newly_supported_families(self):
        api=self.api()
        games=[{'native_identity':'rp_1','public_demo_url':'a'},{'native_identity':'rp_2','public_demo_url':'b'}]
        states={'rp_1':{'state':'needs_contract','revision':'old','client_class':'supported'},
                'rp_2':{'state':'needs_contract','revision':'old','client_class':'still_missing'}}
        self.assertEqual([g['native_identity'] for g in api.select_candidates(games,states,'new',reviewed_families={'supported'})],['rp_1'])

if __name__=='__main__':unittest.main()
