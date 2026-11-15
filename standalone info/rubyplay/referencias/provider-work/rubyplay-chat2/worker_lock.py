"""OS-backed local worker lock; process exit releases it, never deletes journals."""
from contextlib import contextmanager
import re,msvcrt
from har_probe import ROOT

@contextmanager
def worker_lock(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('invalid_worker_lock_name')
    folder=ROOT/'private/worker-locks';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(name+'.lock')).open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise RuntimeError('worker_already_running_'+name) from error
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
