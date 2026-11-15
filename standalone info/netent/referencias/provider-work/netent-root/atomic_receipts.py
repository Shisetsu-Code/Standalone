"""Retry only atomic file replacement when Windows briefly holds a reader lock."""
import json,os,time,uuid
from pathlib import Path

def write_json(path,value,*,replace=None,attempts=20,delay=.05):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        for attempt in range(attempts):
            try:(replace or os.replace)(temporary,path);return
            except PermissionError:
                if attempt+1==attempts:raise
                time.sleep(delay)
    finally:
        try:temporary.unlink(missing_ok=True)
        except PermissionError:pass
