import json,re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from pathlib import Path

class Links(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.current=None;self.buttons=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a':self.current={'href':a.get('href',''),'label':'','class':a.get('class','')}
        if 'data-query-element-id' in a or tag=='button' and ('load' in str(a).lower() or 'page' in str(a).lower()):self.buttons.append(a)
    def handle_data(self,s):
        if self.current:self.current['label']+=s
    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            self.current['label']=' '.join(self.current['label'].split())[:120];self.rows.append(self.current);self.current=None

root=Path(__file__).resolve().parent
for name in ('0-165.html','0-325.html','0-502.json','0-553.json','0-586.json','2-133.html','2-341.html'):
    raw=(root/'private'/'har-documents'/name).read_text(encoding='utf8')
    data=json.loads(raw) if name.endswith('.json') else None
    html=data.get('html','') if data else raw
    parser=Links();parser.feed(html)
    paths={}
    for a in parser.rows:
        path=urlsplit(a['href']).path
        if any(x in path for x in ('/slots/','/soft/','rubyplay.com/','/games','/brand/')) or not a['href'].startswith(('http','javascript','#')):
            paths.setdefault(path,{'label':a['label'],'class':a['class']})
    print(name,'links',len(parser.rows),'paths',len(paths))
    print(json.dumps(list(paths.items())[:12],ensure_ascii=False))
    if data:
        q=data.get('updated_query',{});print('query_page',{k:q.get(k) for k in ('element_id','count','max_num_pages','start','end')},'paged',q.get('query_vars',{}).get('paged'))
    print('loops',[{k:a.get(k) for k in ('data-query-element-id','data-page','data-max-pages','data-start','data-end')} for a in parser.buttons])
    print('pagination_links',[(a['href'],a['label']) for a in parser.rows if any(k in a['class'].lower() for k in ('page','pagi','next'))][:25])
