"""Slot contracts in the older shared casino client, scoped to an explicit game registration."""
import re,hashlib
def metadata(source,gid):
 if not re.fullmatch('[A-Za-z0-9_-]+',gid) or not re.search(r'\.games\.'+re.escape(gid)+r'=\{',source):raise ValueError('Classic slot game registration absent')
 conversion=r'for\(let ([A-Za-z_$][\w$]*) in ([A-Za-z_$][\w$]*)\.config\.bet\)([A-Za-z_$][\w$]*)\[\1\]=Math\.round\(\2\.config\.bet\[\1\]\*\2\.config\.subunits\)'
 if not re.search(conversion,source) or not re.search(r'\.options=\{bets:.*?\},[A-Za-z_$][\w$]*\.command="spin"',source):raise ValueError('Classic native line dictionary/spin wire not proved')
 zero=bool(re.search(r'([A-Za-z_$][\w$]*)\.result&&\1\.result\.total\?\1\.result\.total:0',source))
 finish=bool(re.search(r'\.request\(\{command:"finish"\}',source))
 if not zero or not finish:raise ValueError('Classic result/finish rule not proved')
 return dict(protocol='legacy-v1-slots',source_verified=True,client_family='classic-casino',classic_game_id=gid,source_sha256=hashlib.sha256(source.encode()).hexdigest(),v1_result_total_verified=zero,finish_command_verified=finish,line_bet_contract='Source recountBet builds indexed per-line dictionary; wire multiplies normalized line values by currency subunits. Adapter sends original native line_bets without conversion.',classic_evidence='Explicit game registration in shared official casino.min.js, native indexed bets/spin envelope, missing result means zero, finish command with no options')
