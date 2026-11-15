"""Payloads read from Jungle Spirit's native animal and gamble selectors."""
def jungle_choice(profile,game,previous):
    animal=profile['animal']
    if animal not in {'3','4','5','6','7'} or type(profile['gamble']) is not bool:
        raise ValueError('Unreviewed native animal or gamble choice')
    if game.get('featuredAnimal') is None:return {'featureBuy':False,'animal':animal}
    gamble=profile['gamble'] and not any(p.get('gamble') is True for p in previous)
    return {'featureBuy':False,'gamble':gamble}
