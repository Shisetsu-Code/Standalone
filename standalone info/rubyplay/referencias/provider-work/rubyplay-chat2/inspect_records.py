from catalog_dom import DOM
from har_probe import ROOT,FILES
import json
from collections import Counter

for name in ('0-325.html','2-133.html','2-217.html','2-341.html','2-401.html'):
    dom=DOM((ROOT/'private'/'har-documents'/name).read_text(encoding='utf8')).root
    if name.startswith('0'):
        print(name,'data_keys',dict(Counter(k for n in dom.walk() for k in n.attrs if k.startswith('data-'))))
    cards=[n for n in dom.walk() if n.tag=='a' and n.has('slotPageOverlay-link')]
    print(name,'overlay_cards',len(cards))
    for n in cards[:2]:
        a=n;anc=[]
        for _ in range(6):
            if a is None:break
            anc.append({'tag':a.tag,'id':a.attrs.get('id'),'class':a.attrs.get('class')});a=a.parent
        print('ancestors',anc)
    print('primary_candidates',[(n.attrs.get('id'),n.attrs.get('class')) for n in dom.walk() if n.attrs.get('id') and any(x in n.attrs['id'].lower() for x in ('slot','game','pagi'))][:20])
raw=json.loads(FILES[2].read_text(encoding='utf-8-sig'))
for i in (133,217,239,316,341,401):
    req=raw['log']['entries'][i]['request'];pd=req.get('postData',{})
    print('request',i,req['method'],'post_names',[x.get('name') for x in pd.get('params',[])], 'text_shape',pd.get('text','')[:180] if 'token' not in pd.get('text','').lower() else '[withheld]')
