import json,tempfile,unittest,os
from pathlib import Path
from atomic_receipts import write_json

class AtomicReceiptTests(unittest.TestCase):
    def test_transient_windows_reader_lock_does_not_lose_the_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receipt.json';path.write_text('{"old":true}',encoding='utf8');attempts=[]
            def replace(source,target):
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('Reader holds file')
                os.replace(source,target)
            write_json(path,{'state':'sent_or_uncertain'},replace=replace,delay=0)
            self.assertEqual(json.loads(path.read_text(encoding='utf8')),{'state':'sent_or_uncertain'})
            self.assertEqual(len(attempts),3)

    def test_persistent_lock_keeps_previous_valid_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receipt.json';path.write_text('{"old":true}',encoding='utf8')
            def blocked(*args):raise PermissionError('Still locked')
            with self.assertRaises(PermissionError):write_json(path,{'new':True},replace=blocked,attempts=2,delay=0)
            self.assertEqual(json.loads(path.read_text(encoding='utf8')),{'old':True})
