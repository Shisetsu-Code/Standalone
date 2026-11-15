"""Published native gamble controls; mappings from the captured common client."""


def options(features):
    games=[f for f in features if f['featureID']=='GAMBLE']
    if not games:return []
    if len(games)!=1:raise ValueError('multiple_risk_contracts')
    kind=games[0]['featureClassName']
    if kind=='GambleBTDFeature':return [{'type':'BTD_Gamble_Action','field':'player_choice','value':i,'label':'Carta '+str(i+1)} for i in range(4)]
    if kind=='GambleNoChoiceFeature':return [{'type':'Color_Gamble_Action','field':'color','value':'BLACK','label':'Riesgo sin elección'}]
    if kind=='GambleChooseFeature':return [{'type':'Color_Gamble_Action','field':'color','value':v,'label':v} for v in ('RED','BLACK')]
    if kind=='GambleCardsFeature':
        return [{'type':'Color_Gamble_Action','field':'color','value':v,'label':v} for v in ('RED','BLACK')]+[{'type':'Suit_Gamble_Action','field':'suit','value':v,'label':v} for v in ('SPADES','CLUBS','DIAMONDS','HEARTS')]
    raise ValueError('unrecognized_risk_contract:'+kind)
