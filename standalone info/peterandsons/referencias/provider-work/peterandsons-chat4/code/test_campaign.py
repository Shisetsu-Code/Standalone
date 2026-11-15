import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import campaign

class CampaignTransportTests(unittest.TestCase):
    def test_blocking_response_is_journalled_and_never_retried(self):
        area=campaign.ROOT/'private/test-artifacts';area.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as temporary:
            with patch.object(campaign,'ROOT',Path(temporary)):
                client=campaign.Client({'game_id':'royal-hunt','wallet':'demo-preview'})
                response=Mock(status_code=429);response.json.return_value={'error':'rate_limited'}
                client.session=Mock();client.session.post.return_value=response
                with self.assertRaisesRegex(ValueError,'provider_block_429'):client.call('/cfg',{'key':'synthetic-secret'},'test')
                self.assertTrue((Path(temporary)/'private/remote-block.json').exists())
                with self.assertRaisesRegex(ValueError,'block_retained'):client.call('/cfg',{},'different-intent')
                self.assertEqual(client.session.post.call_count,1)
                record=json.loads((client.folder/'test.json').read_text())
                self.assertEqual(record['request']['key'],'[REDACTED]')
                self.assertEqual(record['http_status'],429)

    def test_unknown_operation_never_reaches_network(self):
        client=campaign.Client({'game_id':'royal-hunt','wallet':'demo-preview'});client.session=Mock()
        with self.assertRaisesRegex(ValueError,'not_reviewed'):client.call('/unknown',{},'never')
        client.session.post.assert_not_called()

    def test_held_paid_round_is_never_replayed_when_processing_other_games(self):
        area=campaign.ROOT/'private/test-artifacts';area.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as temporary:
            root=Path(temporary)
            game={'id':'Gold-raiders','game_id':'gold-raiders','title':'Gold Raiders','wallet':'demo-preview','classification':'slot','valid_public_demo_link':True}
            for folder in ['results','private/holds','private/rounds']:(root/folder).mkdir(parents=True,exist_ok=True)
            (root/'results/catalogue.json').write_text(json.dumps([game]))
            (root/'private/holds/gold-raiders.json').write_text('{"reason":"settlement_rejected"}')
            (root/'private/rounds/gold-raiders--buy_BONUS.json').write_text('{"status":"needs_review"}')
            with patch.object(campaign,'ROOT',root),patch.object(campaign,'Client') as client:
                campaign.run()
                client.assert_not_called()
            self.assertEqual(json.loads((root/'private/checkpoint.json').read_text())['status'],'campaign_finished_with_holds')

if __name__=='__main__':unittest.main()
