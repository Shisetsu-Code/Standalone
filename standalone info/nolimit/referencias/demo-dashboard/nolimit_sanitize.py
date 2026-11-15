"""Remove ephemeral demo transport identifiers from every published JSON copy."""
import json
from pathlib import Path
from endorphina_run import write_json
from nolimit_protocol import redact

def sanitize(root):
    count=0
    for path in root.rglob('*.json'):
        if path.name=='audit.json':continue
        original=json.loads(path.read_text(encoding='utf8'));clean=redact(original)
        if clean!=original:write_json(path,clean);count+=1
    print(json.dumps({'sanitized_files':count}))

if __name__=='__main__':sanitize(Path(__file__).resolve().parent/'nolimit')
