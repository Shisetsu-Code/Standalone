"""Keep confirmed progression wagers without counting repeated modes twice."""
def archive_verified_duplicates(proof):
    seen=set();kept=[]
    for case in proof['cases']:
        verified=case.get('state')=='verified' and case.get('passed')
        if verified and case['mode'] in seen:
            proof.setdefault('progression_rounds',[]).append(case)
        else:
            kept.append(case)
        if verified:seen.add(case['mode'])
    proof['cases']=kept
