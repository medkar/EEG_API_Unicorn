"""`core.modes` — le catalogue des modes et leur runtime.

Un **mode** est deux choses posées côte à côte :
  - un `ModeSpec` (contract.py) : ce qu'il est, ce qui s'y règle, ce qu'il publie ;
  - un `ModeRuntime` (runtime.py) : son état vivant — phase, décodeur, publieur.

**L'algorithme et le mode sont séparés.** `core/cca_decoder.py` reste l'algorithme : une CCA,
testable sur du synthétique, indifférente au produit. `modes/ssvep.py` est le contrat : comment ça
s'appelle, ce qui se règle, ce qui se publie. Les mélanger était le défaut de l'ancien `server.py`,
où « un mode » n'était qu'une suite de `if mode == "ssvep" … elif mode == "neuro"`.

Le registre décrit **tous** les modes, y compris ceux que le moteur ne sait pas faire : c'est ce
qui permet à la console de dire « c-VEP : demande un stimulus verrouillé à la frame » au lieu de
faire comme s'il n'existait pas.
"""
