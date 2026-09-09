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
