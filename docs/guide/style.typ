// La mise en page des PDF du guide (pandoc l'insère en tête : outils/construire_guide.py).

// Le code : petit, sur fond clair, jamais coupé à droite (les exemples tiennent sur 100 colonnes).
#show raw.where(block: true): set text(size: 7.4pt)
#show raw.where(block: true): set par(justify: false)
#show raw.where(block: true): it => block(fill: luma(246), inset: 7pt, radius: 3pt,
                                          width: 100%, stroke: 0.4pt + luma(215), it)
#show raw.where(block: false): it => box(fill: luma(238), inset: (x: 2pt), outset: (y: 2pt),
                                         radius: 2pt, it)

// Les tableaux : des filets fins, un en-tête en gras, le texte aligné à gauche et pas justifié
// (pandoc les place dans un cadre centré, dont les cellules hériteraient sinon).
#set table(stroke: 0.4pt + luma(170), inset: 5pt)
#show table.cell: set align(left)
#show table.cell.where(y: 0): set text(weight: "bold")
#show table: set text(size: 9pt)
#show table: set par(justify: false)

// Chaque grande partie commence sur une nouvelle page ; les liens se voient.
#show heading.where(level: 1): it => { pagebreak(weak: true); it }
#show link: set text(fill: rgb("#1f5fbf"))
#set par(justify: true)
