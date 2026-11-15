import json,re
def extract(html):
    for m in re.finditer(r'self\.__next_f\.push\((.*?)\)</script>',html,re.S):
        try:args=json.loads(m.group(1))
        except ValueError:continue
        for item in args:
            if isinstance(item,str) and '"allGames":[' in item:
                games=json.JSONDecoder().raw_decode(item[item.index('"allGames":[')+len('"allGames":'):])[0]
                return [dict(ordinal=i+1,**{k:g.get(k) for k in ['id','title','slug','demo_url','tags']}) for i,g in enumerate(games)]
    raise ValueError('native_catalogue_not_found')
if __name__=='__main__':
    from pathlib import Path
    root=Path(__file__).resolve().parent.parent
    out=extract((root/'private/references/catalogue-live.html').read_text(encoding='utf-8'))
    (root/'results/catalogue.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    print([(g['ordinal'],g['title']) for g in out])
