"""Game-specific inputs verified in official public clients, not guessed fields.

Beam Boys 1.39.0 main.js publishes updateCustomBetData with
{volatility:'low'} or {volatility:'extreme'}. Its casino client copies this
object into bets[0].customData. Both public sources are in hacksaw/reference.
"""


def native_extra(game_id,bonus_id=None,base_mode=None):
    if str(game_id)!='1426':
        if base_mode is not None:raise ValueError('unpublished_game_mode')
        return {}
    mode=bonus_id.rsplit('_',1)[-1] if bonus_id else base_mode or 'low'
    if mode not in ('low','extreme') or base_mode is not None and base_mode!=mode:raise ValueError('unpublished_or_conflicting_volatility')
    return {'customData':{'volatility':mode}}


def mode_cases(game):
    if str(game['id'])!='1426':return []
    return [dict(game,kind='purchase',case=game['id']+'--mode-extreme',base_mode='extreme',control_type='mode',label='Modo Extreme')]
