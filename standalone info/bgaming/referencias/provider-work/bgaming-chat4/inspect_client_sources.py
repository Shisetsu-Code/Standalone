"""Read private static JS/HTML without exposing live URL query values."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
import re
class Scripts(HTMLParser):
 def handle_starttag(self,tag,attrs):
  if tag in ('script','link'):
   d=dict(attrs);u=d.get('src',d.get('href'))
   if u:print(tag,urlsplit(u).path)
if __name__=='__main__':
 import sys
 for gid in sys.argv[1:]:
  print(gid);root=Path(__file__).resolve().parent.parent.parent/'bgaming-private-chat4/research/frontends'/gid;Scripts().feed((root/'index.html').read_text(encoding='utf8'))
  if (root/'game.js').exists():
   s=(root/'game.js').read_text(encoding='utf8')
   for word in ['getRequestByKey','getRequestData','buildSpinRequest','spinRequest','SHARED_CONTROLS_ON_CLICK_BUY','buyBonus','RequestMap']:
    print(word)
    for m in list(re.finditer(re.escape(word),s))[:3]:print(s[max(0,m.start()-70):m.start()+240])
