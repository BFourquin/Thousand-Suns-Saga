
def localized_name(document, language):
    # The game data doesn't have all its English names yet : French rather than "None" on the screen
    return document.get('name_' + language) or document.get('name_fr')
