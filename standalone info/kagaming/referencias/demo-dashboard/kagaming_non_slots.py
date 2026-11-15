"""Offline separate non-slot inventory; native evidence is read, never rewritten."""
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote

USER_INSTRUCTION='Dejar fuera lo que no sea slot; documentarlo y conservarlo en una lista separada. Prioridad a slots.'
REASON='Fuera del recorrido actual por pedido del usuario: solo slots. No se realizarán más pruebas de estos juegos.'


def render(folder,*,audit=None,source_root=None):
    """Write only three derived reports in the explicit folder, without gameplay.

    Optional audit/source_root arguments support offline test fixtures. The
    production auditor is called once for each recorded verified case, with
    this folder's initialization and the corresponding local source text.
    """
    folder=Path(folder)
    catalog=json.loads((folder/'catalog.json').read_text(encoding='utf8'))
    games=[g for g in catalog if g['gameType']!='slots']
    if audit is None:
        from kagaming_audit import audit_case
        audit=audit_case
    source_root=Path(source_root) if source_root is not None else Path(__file__).parent/'kagaming/reference'
    scope=json.loads((folder/'scope.json').read_text(encoding='utf8')) if (folder/'scope.json').exists() else {}
    instruction=scope.get('user_instruction',USER_INSTRUCTION)
    result={'scope':'Juegos que no son slots; evidencia previa conservada por separado.',
            'user_instruction':instruction,'further_testing':'stopped','reason':REASON,'games':[]}
    audited=[]
    tracepaths=sorted((folder/'traces').glob('*.json'))
    for game in games:
        gid=game.get('id',game.get('gameId'))
        row={key:game[key] for key in ('ordinal','gameType')}
        row.update(id=gid,name=game.get('name',game.get('gameName',gid)),
                   further_testing='stopped',reason=REASON,records=[])
        for path in tracepaths:
            if not path.name.startswith(gid+'-'):
                continue
            raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            record={'file':path.name,'link':'traces/'+path.name,'sha256':digest,'bytes':len(raw)}
            try:
                case=json.loads(raw.decode('utf8'))
                record.update(mode=case.get('mode'),status=case.get('status'),
                              key=case.get('profile',{}).get('key'))
                if case.get('game')!=gid:
                    raise ValueError('non_slot_trace_game_mismatch')
                if case.get('status')=='verified':
                    initialization=json.loads((folder/'initializations'/(gid+'.json')).read_text(encoding='utf8'))
                    source=(source_root/(gid.lower()+'.js')).read_text(encoding='utf8')
                    checked=audit(case,initialization,source)
                    if not isinstance(checked,dict) or type(checked.get('passed')) is not bool:
                        raise ValueError('invalid_individual_native_audit_result')
                    record['audit']=checked
            except Exception as error:
                record['audit']={'passed':False,'error':str(error)}
                record.setdefault('status','unreadable_record')
            if record.get('status')=='verified' or 'audit' in record:
                audited.append(dict(record.get('audit',{'passed':False,'error':'missing_individual_audit'}),game=gid,file=path.name,sha256=digest))
            row['records'].append(record)
        row['recorded_normal_count']=sum(r.get('mode')=='normal' for r in row['records'])
        row['recorded_special_count']=len(row['records'])-row['recorded_normal_count']
        row['verified_normal_count']=sum(r.get('mode')=='normal' and r.get('status')=='verified' for r in row['records'])
        row['verified_special_count']=sum(r.get('mode')!='normal' and r.get('status')=='verified' for r in row['records'])
        row['recorded_cases']=len(row['records'])
        result['games'].append(row)
    auditdoc={'scope':'Auditoría individual de casos previos verificados; sin nuevas pruebas.',
              'passed':all(r.get('passed') is True for r in audited),
              'verified_cases':sum(r.get('status')=='verified' for g in result['games'] for r in g['records']),
              'cases':audited}
    escape=lambda value:html.escape(str(value),quote=True)
    page=['<!doctype html><html lang="es"><meta charset="utf-8"><title>KA Gaming · Fuera de slots</title>',
          '<style>body{font:17px system-ui;background:#101827;color:#e2e8f0;margin:35px}a{color:#7dd3fc}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #334155}small{color:#a8b7cc}</style>',
          '<h1>Juegos que no son slots · lista separada</h1>',
          '<p>Pedido del usuario: «'+escape(instruction)+'»</p><p>'+escape(REASON)+'</p>',
          '<p>Se conservan todos los registros previos. No se completarán partidas ni variantes pendientes. Los juegos sin registros permanecen sin probar.</p>',
          '<p><a href="index.html">Volver a slots</a> · <a href="non-slots.json">Lista y huellas de los archivos</a> · <a href="non-slots-audit.json">Auditoría individual</a></p>',
          '<table><thead><tr><th>#</th><th>Juego</th><th>Tipo</th><th>Casos previos</th><th>Estado</th><th>Registros conservados</th></tr></thead><tbody>']
    for game in result['games']:
        links=[]
        for record in game['records']:
            label=record.get('key') or record.get('mode') or record['file']
            auditlabel=(' · auditoría correcta' if record['audit'].get('passed') else ' · auditoría requiere revisión') if 'audit' in record else ''
            links.append('<a href="'+quote(record['link'],safe='/')+'">'+escape(label)+'</a> · '+escape(record['status'])+escape(auditlabel))
        values=[game['ordinal'],escape(game['name']),escape(game['gameType']),
                str(game['recorded_normal_count'])+' normales · '+str(game['recorded_special_count'])+' especiales',
                'Detenido · sin más pruebas' if links else 'Sin pruebas registradas · fuera del recorrido',
                ('<details><summary>'+str(len(links))+' casos conservados</summary>'+'<br>'.join(links)+'</details>') if links else '—']
        page.append('<tr>'+''.join('<td>'+str(v)+'</td>' for v in values)+'</tr>')
    page.append('</tbody></table></html>')
    for name,data in [('non-slots.json',result),('non-slots-audit.json',auditdoc)]:
        (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (folder/'non-slots.html').write_text(''.join(page),encoding='utf8')
    return result
