# Pulsar V14

V14 est la version active de Pulsar.

Le code V14 conserve le socle probabiliste validé de V13.10 et ajoute uniquement les signaux contextuels retenus : starter, lineup/matchup et bullpen, avec garde-fous PIT et plafonnement des corrections.

## Principes

- une seule distribution cohérente pour ML, run line et totals ;
- aucune cote bookmaker utilisée comme feature prédictive ;
- données pré-match uniquement en production ;
- données manquantes = aucune correction inventée ;
- corrections contextuelles plafonnées ;
- V13.10 est gelée comme référence de rollback, pas comme modèle développé en parallèle.

## Modules de production

- `run_stack.py` : socle de runs hérité du champion ;
- `park.py` : facteur de parc ;
- `context_overlay.py` : starter, lineup/matchup, bullpen et micro-signaux disponibles ;
- `v13_context_adapter.py` : adaptation temporaire du feature store PIT existant ;
- `distribution.py` : distribution des scores et probabilités ;
- `market_edge.py` : fair odds, no-vig, edge et EV ;
- `feature_row.py` : sélection stricte des snapshots pré-match ;
- `preflight.py` / `validation.py` : invariants de sécurité.

Les scripts de backtest ponctuels, rapports d'audit, shadow scaffolding et documentation de migration ne font pas partie de la version de production.
