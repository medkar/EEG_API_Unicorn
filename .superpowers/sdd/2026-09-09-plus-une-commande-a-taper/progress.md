# SDD ledger — plan: docs/superpowers/plans/2026-09-09-plus-une-commande-a-taper.md

Chantier « plus une seule commande à taper ». Spec `f12ff78`, plan `79508cf`/`fef9f43`.

**Mode d'exécution choisi par l'utilisateur (2026-09-09) : HYBRIDE, sans point d'arrêt, et il veut
MINIMISER LE TEMPS.** Donc **quatre dispatches seulement** (contre huit au chantier précédent) :

| tâche | qui |
|---|---|
| T1 test d'inventaire + CLAUDE.md | **en ligne** — le scanner de `server.py` est du terrain connu |
| T2 `MesureRuntime` | sous-agent |
| T3 contrôle alpha de bout en bout | sous-agent |
| T4 source à l'ouverture | **en ligne** |
| T5 options de lancement + journal | **en ligne** |
| T6 page « flux sortant » | **en ligne** |
| T7 enregistrement de séance | **en ligne** |
| T8+T9 SSVEP de bout en bout | sous-agent (un seul brief, fenêtre + mesure) |
| T10 les retraits | sous-agent — piège d'ordre sur `ui.py` |
| T11 documentation | **en ligne**, relue |

⚠️ **T1 se termine ROUGE, volontairement**, en nommant six fichiers. T10 doit le rendre VERT.

## Journal

- **T1 : complete** — `e293dbd`, en ligne. Le scan de `research/` est ROUGE sur six fichiers, comme
  voulu : `alpha_check`, `live_ssvep`, `ssvep_analyze`, `ssvep_guided`, `ssvep_stimulus`, `ui`.
  ⚠️ **Six, pas cinq** : `ui.py` s'est ajouté à l'inventaire, et huit fichiers de `archive/`
  l'importent. La contrainte est aussi entrée dans `CLAUDE.md`.
- **T2 : complete** — `ea0c6b6`, sous-agent. `MesureRuntime` + refus d'une 2e activité dans les deux
  sens et aux deux instants. Réserve portée : `etape` reste vide sur une mesure, donc un
  `_maybe_beep` recopié serait muet.
- **T3 : complete** — `c4f3973`→`9399dbd`, sous-agent. Contrôle alpha de bout en bout. **Deux gardes
  que l'original n'avait pas** : le détrend est tenu (sans lui un offset DC de 10⁵ µV fait tomber le
  ratio de 4,44 à 2,26 et ferait échouer toute séance, casque parfait compris), et quatre voies
  plates sont refusées (leur ratio 10⁻²⁷/10⁻²⁷ franchissait la barrière une fois sur deux — « le
  montage est bon » sur un câble débranché). Le top sonore est assis sur `classe`, pas `etape`.
  ⚠️ Il a archivé `alpha_check.py` lui-même : la T10 n'a plus que deux fichiers à archiver.
  Compteur : **six → cinq**.
- **T4 : complete** — `b91b1a0`, en ligne. Écran de départ, aucun repli automatique.
  ⚠️ Vérifié : **aucun repli n'existait déjà** dans `acquisition.py`/`server.py` — la garde sert à
  empêcher qu'on en ajoute un.
- **T5 : complete** — `3e3a51d`, en ligne. Options de lancement + case « Journal de séance »,
  cochée par défaut, et seulement là où le registre déclare que la fenêtre sait journaliser.
  ⚠️ Seul le c-VEP a `--log` ; le P300 et l'ErrP ne l'ont pas, et ce n'est pas un oubli.
  `seances/` gitignoré, hors de `data/`.
- **Correctif hors plan** — `36fdc5c` : le test de cadence c-VEP rougissait 1 fois sur 3 (cause
  connue depuis la revue du 2026-09-08, jamais corrigée). Borne inférieure au lieu d'une égalité ;
  la garde mord toujours (0 cale → rouge), six lancements propres après.

## Réserve à porter

- 🔴 **La T3 a empiété sur la T10** en archivant `alpha_check.py`. C'est justifié (le compteur ne
  pouvait pas bouger autrement) mais la T10 doit en tenir compte : il lui reste `live_ssvep.py`,
  `ssvep_analyze.py`, `ssvep_guided.py` (après T8/T9) et surtout **`ui.py`, dont l'ordre est
  contraint**.
