"""Native Street Fighter opponent selection from the current demo initialization."""
PLAYABLE={'RYU','BLANKA','CHUNLI','DHALSIM','GUILE','EHONDA','KEN','ZANGIEF'}

def character_parameters(initial,character):
    if character not in PLAYABLE:raise ValueError('Unplayable native character')
    offered=initial.get('spinInfo.randomOpponents','').split(',')
    opponent=next((v for v in offered if v in PLAYABLE and v!=character),None)
    if opponent is None:raise ValueError('No native opponent offered')
    return {'character':character,'opponent':opponent}
