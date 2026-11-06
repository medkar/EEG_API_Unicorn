"""La version du produit, écrite à UN seul endroit.

La CI lit la ligne ci-dessous avec le motif `^VERSION = ".*"$` et refuse de construire une
version dont le tag n'est pas `v` suivi de cette valeur (elle ne la réécrit pas) : la ligne doit
rester seule, sous cette forme exacte. Pour une nouvelle version, on change cette ligne, puis on
pose le tag.
"""
VERSION = "1.0.0"
