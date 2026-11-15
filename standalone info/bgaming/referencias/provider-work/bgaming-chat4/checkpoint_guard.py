"""Prevent concurrent runners and blind replacement of an interrupted game's evidence."""
import os
def acquire(path):
 handle=open(path,'a+b');handle.seek(0,2)
 if handle.tell()==0:handle.write(b'\0');handle.flush()
 handle.seek(0)
 try:
  if os.name=='nt':
   import msvcrt
   msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
  else:
   import fcntl
   fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 except OSError:
  handle.close();raise RuntimeError('Another QA runner holds the process lock; do not start a second instance') from None
 return handle
def require_inactive(state):
 if state.get('active_game') is not None:raise RuntimeError('Interrupted/active game checkpoint must be reviewed before starting a new session: '+str(state['active_game']))
