"""Read-only recognition of current official client contracts."""
import re,hashlib,json
def gamble_action(state,source):
    if state.get('NextMode')!='root' or state.get('FreeSpinsLeft',0)!=0 or state.get('waitForAcceptWin') is not True:return None
    if 'const e="red"===t?0:1;this.app.request.send({name:"Gamble",body:{sid:app.request.sid,data:e}})' not in source or 'this.data.win.total=t.Balance.TotalWinCents/100' not in source or 'this.data.gamble.exitAfterLoose=!0,this.gambleExit()' not in source:return None
    return {'data':0}
def opened_positions(packets):
    opened=set()
    for p in packets:
        if p.get('http_status')!=200:continue
        q=p.get('request',{}).get('user_input')
        if isinstance(q,dict) and isinstance(q.get('X'),int) and isinstance(q.get('Y'),int):opened.add((q['X'],q['Y']))
        x=p.get('response',{});board=x.get('Screen')
        if x.get('Mode')=='bonus' and isinstance(board,list) and len(board)==4 and all(isinstance(r,list) and len(r)==5 for r in board):
            for y,row in enumerate(board):
                for col,value in enumerate(row):
                    if value is not None:opened.add((col,y))
    return [{'X':x,'Y':y} for x,y in sorted(opened)]
def bonus_choice(state,source,opened=None):
    if state.get('NextMode')!='bonus' or state.get('Mode') not in ('root','rootCascade','bonus'):return None
    if not all(t in source for t in ['for(let t=0;t<4;t++)for(let e=0;e<5;e++)','locationPoint:{X:e,Y:t}','user_input:{...t}','this.notify(fE.BONUS_ROLL,e.locationPoint)','e.openState!==bE']):return None
    seen={(q['X'],q['Y']) for q in opened or []}
    board=state.get('Screen') if state['Mode']=='bonus' else [[None]*5 for _ in range(4)]
    if not isinstance(board,list) or len(board)!=4 or any(not isinstance(row,list) or len(row)!=5 for row in board):return None
    for y,row in enumerate(board):
        for x,value in enumerate(row):
            if value is None and (x,y) not in seen:return {'X':x,'Y':y}
    return None
def next_action(state,source,opened=None):
    if bonus_choice(state,source,opened) is not None:return '_Roll'
    if state.get('NextMode')=='root' and state.get('FreeSpinsLeft',0)==0 and state.get('waitForAcceptWin') is True and 'name:"AcceptWin",body:{sid:app.request.sid}' in source and 'acceptwin(t){this.data.balance.cash=t.Balance.ScoreCents/100' in source:return '_AcceptWin'
    return '_Roll' if roll_continuation(state,source) else None
def roll_continuation(state,source):
    legacy_book='game.request.sendRoll({value:e.value.current})' in source and 'i=t.index,a=void 0===i?0:i' in source and 'if(this.state.isFS)return null;if(this.state.isRespin)return null' in source
    if legacy_book and state.get('waitForAcceptWin') is not True and isinstance(state.get('NextMode'),str):
        nxt=state['NextMode']
        if 'respin' in nxt and 'state.next.includes("respin")' in source:return True
        if nxt.startswith('fs') and 'state.next.includes("fs")' in source:return True
    legacy_default='this.game.request.sendRoll({value:this.data.balance.value.current,level:this.data.balance.level.current})' in source and 'i=t.index,o=void 0===i?0:i' in source and 'this.state.isFS?null:this.state.isRespin?null' in source
    if legacy_default and state.get('waitForAcceptWin') is not True:
        named=set(re.findall(r'"([A-Za-z0-9_-]+)"==[\w$]+\.NextMode',source))-{'root'}
        if state.get('NextMode') in named:return True
        if isinstance(state.get('NextMode'),str) and 'FS' in state['NextMode'] and re.search(r'\b[\w$]+\.NextMode\.includes\("FS"\)',source):return True
    actions=set(re.findall(r'name:"([A-Z][A-Za-z]+)",body:',source))
    automatic_actions={'Initialise','Roll','BuyBonus','Ping','Gamble','GambleHistory','AcceptWin'}
    omitted_automatic='waitForAcceptWin' not in state and state.get('NextMode')!='root' and 'Roll' in actions and actions<=automatic_actions and 'parseGamble(t){this.data.waitForAcceptWin=t.waitForAcceptWin}' in source
    if not omitted_automatic:
        omitted_automatic='waitForAcceptWin' not in state and state.get('NextMode')!='root' and 'Roll' in actions and actions<= {'Initialise','Roll','BuyBonus','Ping'} and 'waitForAcceptWin' not in source and 'this.root_names=[' in source and 'this.fs_names=[' in source
    if state.get('waitForAcceptWin') is not False and not omitted_automatic:return False
    if state.get('NextMode')=='freespins_alternative' and state.get('Mode') in ('root','rootCascade') and 'this.isFirstRound="root"===this.state.mode||"rootCascade"===this.state.mode' in source and re.search(r'sendRollRequest\(\)\{this.isFirstRound\?\(this.notify\([\w$]+\.ROLL_REQUEST\)',source) and re.search(r'subscribe\([\w$]+\.ROLL_REQUEST,this.roll.bind\(this\)\)',source):return True
    if state.get('NextMode') in ('rootCascade','freespins','fsCascade','fsRespin'):return True
    # A current game may name its automatic roll phases differently. Accept
    # literal root/bonus groups declared by that saved client only, and exclude
    # clients with interactive endpoints or user-supplied bonus decisions.
    if actions<=automatic_actions and 'user_input' not in source and 'name:"Roll",body:{sid:this.sid,denomination:' in source:
        declared=set()
        for text in re.findall(r'this\.(?:root|bonus|root_names|fs_names|respin_names)=(\[[^\]]*\])',source):
            try:values=json.loads(text)
            except ValueError:
                values=[]
                for token in text[1:-1].split(','):
                    token=token.strip();ref=re.fullmatch(r'([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)',token)
                    if ref:
                        owner,key=map(re.escape,ref.groups());found=set(re.findall(r'\b'+owner+r',"'+key+r'","([a-zA-Z0-9_-]+)"',source))
                        if len(found)==1:values.extend(found)
                    elif re.fullmatch(r'"[a-zA-Z0-9_-]+"',token):values.append(json.loads(token))
            if isinstance(values,list) and all(isinstance(v,str) for v in values):declared.update(values)
        for _,native,alias in re.findall(r'changeNewStates\(([a-z])\)\{return"([A-Za-z0-9_-]+)"===\1\?"([A-Za-z0-9_-]+)":\1\}',source):
            if alias in declared:declared.add(native)
        if state.get('NextMode') in declared-{'root'}:return True
    return False
def identify(source):
    matches=set(re.findall(r'modes:\[\{name:"root",mode:"([a-zA-Z0-9_-]+)"',source))
    services=set(re.findall(r'serviceURL:"(https://expo\.bossgs\.net/service)"',source))
    native_origin=bool(re.search(r'get serviceURL\(\)\{[^{}]{0,600}window\.location\.origin',source))
    if len(matches)!=1 or not (native_origin or len(services)==1):raise ValueError('unrecognized_native_client')
    modern='lines:this.data.linesCount' in source
    modern_buy='requestBuyBonus(){this.send({name:"BuyBonus"' in source
    old_lines_buy='game.request.sendBonusBuyPOST({type:"BuyBonus",body:{sid:game.request.sid,denomination:game.data.balance.value.current,betlevel:game.data.balance.level.current,lines:game.data.lines.length,data:0}})' in source
    old_fixed_buy=bool(re.search(r'/_BuyBonus"\),type:"ROLL",timeout:15e3,body:\{sid:this.sid,denomination:[a-z],betlevel:1,data:0\}',source))
    return {'slotcode':matches.pop(),'service_base':services.pop() if services else None,'roll_lines':modern,'buy_bonus_contract':modern_buy or old_lines_buy or old_fixed_buy,'buy_lines':modern_buy or old_lines_buy,'buy_fixed_level_one':old_fixed_buy,'named_buy_contract':bool(re.search(r'requestBuyBonus\(([a-z])\)\{this.send\(\{name:"BuyBonus",body:\{buyBonusCode:\1,sid:this.sid',source)),'client_sha256':hashlib.sha256(source.encode()).hexdigest(),'sid_policy':'new_native_dev_timestamp_never_HAR'}
