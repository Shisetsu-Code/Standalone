"""HTML tree for public catalogue metadata; scripts are never executed."""
from html.parser import HTMLParser
from dataclasses import dataclass,field

@dataclass
class Node:
    tag:str
    attrs:dict=field(default_factory=dict)
    children:list=field(default_factory=list)
    parent:object=None
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child,Node):yield from child.walk()
    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c,Node) else c for c in self.children).split())
    def has(self,cls):return cls in self.attrs.get('class','').split()

class DOM(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.root=Node('root');self.stack=[self.root];self.feed(html)
    def handle_starttag(self,tag,attrs):
        n=Node(tag,dict(attrs),parent=self.stack[-1]);self.stack[-1].children.append(n)
        if tag not in self.VOID:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:del self.stack[i:];return
    def handle_data(self,text):self.stack[-1].children.append(text)

if __name__=='__main__':
    from pathlib import Path
    root=Path(__file__).resolve().parent
    for name in ('0-325.html','2-133.html','2-341.html','2-217.html'):
        tree=DOM((root/'private'/'har-documents'/name).read_text(encoding='utf8')).root
        anchors=[n for n in tree.walk() if n.tag=='a']
        provider=[{'href':n.attrs.get('href'),'class':n.attrs.get('class'),'text':n.text()[:70]} for n in anchors if '/soft/Ruby-Play' in n.attrs.get('href','') and n.attrs.get('href','').startswith('/es')]
        cards=[n for n in anchors if '/slots/' in n.attrs.get('href','') or '/games/' in n.attrs.get('href','')]
        print(name,'headings',[(n.tag,n.text()[:90]) for n in tree.walk() if n.tag in ('h1','h2')][:15], 'pagination',provider)
        print('first_cards',[{'a_attrs':n.attrs,'text':n.text()[:70], 'parent_tag':n.parent.tag,'parent_attrs':n.parent.attrs,'images':[c.attrs.get('alt') for c in n.walk() if c.tag=='img']} for n in cards[:3]])
