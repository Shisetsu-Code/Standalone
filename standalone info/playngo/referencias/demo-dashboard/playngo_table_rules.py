"""Shared table transcript boundaries, independent of monetary field schemas."""
def transcript_errors(trace):
    errors=[];entered=False;closed=False
    for step in trace:
        sent=step.get('commands',[])
        if closed and sent:errors.append('table_action_after_native_closure')
        if not entered:
            if any(x['code']==1 for x in sent):entered=True
            elif any(x['code'] not in (103,101,104) for x in sent):errors.append('unexpected_table_pre_entry_command')
        if entered and any(x['code']==52 and len(x['args'])>1 and x['args'][1]=='0' for x in step.get('responses',[])):closed=True
    return errors
