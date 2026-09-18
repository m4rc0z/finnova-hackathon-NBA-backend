# Notice — `client_features.parquet`

Guide d'utilisation du fichier client construit à partir des données du challenge. La référence technique complète,
avec pour chaque colonne sa source, sa couverture et sa plage, est dans `FEATURES.md` (en anglais). Le détail des
fichiers bruts est dans `REAL_DATA_REPORT.md`.

## En bref

| | |
|---|---|
| Contenu | **une ligne par client** : 8 046 clients, 83 colonnes |
| Clé | `individual_id` (UUID, unique) |
| Date de référence | période **24301** (fin de la simulation) |
| Fenêtre des flux | périodes **24290 à 24301**, soit 12 mois |
| Montants | en **CHF** ; les sorties d'argent (loyer, dépenses) sont en **positif** |
| Données personnelles | aucune : ni nom, ni rue, ni numéro, ni NPA ; pas de texte libre |
| Construction | `python scripts/build_client_features.py` (~9 s, depuis `data/real/`) |
| Exploration | `client_features_exploration.ipynb`, dans ce dossier (Colab) |

## Obtenir le fichier

Le parquet est dans ce dossier, à côté de cette notice. Il est dérivé des données des organisateurs ; sa
publication a été autorisée.

- **En local** : lire directement `client_features/client_features.parquet`.
- **Dans Colab** : copier ce fichier dans Google Drive sous `MyDrive/nba-studio/`, puis ouvrir le notebook. Il
  monte le Drive et le trouve seul ; sinon, il propose un upload.

Le script de construction (`scripts/build_client_features.py`), `FEATURES.md` et `REAL_DATA_REPORT.md` ne sont
pas dans ce dépôt.

## Lire le temps : les « périodes »

Une période est un **mois**, codé en entier. Les données couvrent 13 périodes, de 24289 à 24301 :

- **24289** : état d'ouverture (soldes initiaux) ;
- **24290 à 24301** : 12 mois d'activité.

Lecture probable, pas encore confirmée par les organisateurs : `période = 12 × année + mois`, soit de janvier 2024
(24289) à janvier 2025 (24301). L'indice le plus fort : tous les 13e salaires tombent en 24300, c'est-à-dire en
décembre selon cette lecture. En pratique, `24301 − période` = nombre de mois écoulés avant la date de référence.

## Les colonnes, famille par famille

### Profil (qui est le client ?)

| colonne | ce que c'est |
|---|---|
| `age_years` | âge en années à la date de référence |
| `sex` | F ou M |
| `canton`, `city` | canton (26 codes) et commune, à jour après un déménagement |
| `nationality` | swiss, eu_efta, other |
| `education_level` | mandatory, apprenticeship, matura, university |
| `occupation` | métier (99 intitulés en allemand) |
| `sector` | secteur du métier dans le profil **initial** ; pas mis à jour au changement d'emploi, préférer `employer_sector` |
| `marital_status` | single, married, divorced, widowed |
| `employment_type` | employed, retired, student, self_employed (vide pour 5 %) |
| `risk_appetite` | appétit pour le risque, de 0 à 1 (médiane 0) |
| `wallet_share` | part du portefeuille financier du client détenue par la banque, de 0 à 1 |
| `big5_openness` … `big5_neuroticism` | personnalité « Big Five », 5 scores de 0 à 100 |
| `health_score`, `n_health_conditions` | score de santé (0–100) et nombre de pathologies déclarées |

### Revenu

| colonne | ce que c'est |
|---|---|
| `income_monthly_chf` | revenu mensuel déclaré (instantané) |
| `salary_monthly_chf` | salaires réellement versés, 13e et bonus compris, en moyenne mensuelle |
| `has_13th_salary`, `has_annual_bonus` | a touché un 13e salaire / un bonus pendant la fenêtre |
| `employer_sector`, `employer_size_band` | secteur et taille (small, medium, large) de l'employeur actuel ; vide sans employeur connu (53 %) |

### Produits détenus (à la date de référence)

| colonne | ce que c'est |
|---|---|
| `n_accounts_open`, `n_accounts_closed` | comptes ouverts aujourd'hui / fermés pendant la simulation |
| `has_checking`, `has_savings`, `has_pillar3a`, `has_credit_card`, `has_investment`, `has_insurance` | détient au moins un compte ouvert de ce type |
| `has_business_account` | détient un compte commercial ouvert (*Geschaeftskonto*) |
| `first_account_period`, `tenure_months` | premier compte, ancienneté en mois (**plafonnée à 12** : les données commencent en 24289) |

Il n'y a pas de colonne « hypothèque » : les comptes hypothécaires de la source sont vides. Pour l'immobilier,
voir `owns_property` et `mortgage_payment_monthly_chf`.

### Soldes

| colonne | ce que c'est |
|---|---|
| `balance_total_chf` | somme des soldes de **tous** les comptes, fermés compris, 3a compris |
| `balance_checking_chf`, `balance_savings_chf`, `balance_pillar3a_chf`, `balance_investment_chf` | solde par type de compte |
| `min_monthly_total_balance_chf` | le plus bas solde total de fin de mois sur l'année (reconstruit à partir des transactions) |
| `months_in_overdraft` | nombre de mois (0–12) où au moins un compte courant finit dans le rouge |

### Flux mensuels (moyennes sur la fenêtre)

Une moyenne mensuelle = total sur la fenêtre ÷ `active_months`, c'est-à-dire le nombre de mois où le client a eu au
moins une transaction. Une hypothèque commencée en cours d'année est donc diluée : 9 paiements de 2 067,70 CHF
donnent 1 550,78 CHF.

| colonne | ce que c'est |
|---|---|
| `active_months` | 0 à 12 |
| `rent_monthly_chf` | loyer |
| `mortgage_payment_monthly_chf` | paiements hypothécaires |
| `pillar3a_contribution_monthly_chf` | versements au 3e pilier |
| `savings_transfer_monthly_chf` | virements **nets** vers l'épargne (peut être négatif) |
| `spend_total_monthly_chf` | dépense de consommation totale, somme des 9 suivantes |
| `spend_food_…`, `spend_restaurants_…`, `spend_transport_…`, `spend_other_…`, `spend_recreation_…`, `spend_health_…`, `spend_clothing_…`, `spend_communication_…`, `spend_education_monthly_chf` | dépense par catégorie |
| `savings_rate` | épargne nette ÷ salaires sur l'année (vide sans salaire) |

### Événements de vie (pendant la fenêtre)

Pour chaque événement : `had_<événement>` (vrai / faux) et `periods_since_<événement>` (mois écoulés depuis le
dernier, vide s'il n'y en a pas eu). Événements : `job_change` (564 clients), `marriage` (152), `divorce` (73),
`birth` (63 parents), `migration` (307), `property_purchase` (5). Pour un mariage, un divorce ou une naissance,
les deux personnes concernées sont comptées.

### Immobilier (profil)

`owns_property` (687 propriétaires), `property_value_chf`, `mortgage_outstanding_chf` (dette restante),
`mortgage_monthly_chf` (mensualité). Ces trois dernières colonnes sont vides pour les non-propriétaires.

### Drapeaux

| colonne | ce que c'est |
|---|---|
| `is_self_employed_with_business_account` | indépendant avec un compte commercial (465) |
| `is_onboarded_during_run`, `onboarded_period` | client arrivé pendant la simulation (1 010), et quand |

### Labels : les cibles à prédire, jamais des variables explicatives

| colonne | ce que c'est |
|---|---|
| `label_exited` | le client a quitté la banque, quelle qu'en soit la raison (362) |
| `label_exit_period` | la période de sortie |
| `label_churn_with_reason` | parti pour un concurrent, avec un motif écrit (278) ; le texte n'est pas dans ce fichier |
| `label_is_death` | décédé (58) |

## Les pièges à connaître avant de modéliser

1. **Les clients sortis sont photographiés après leur sortie.** Aucun des 362 n'a encore un compte ouvert, donc
   leurs `has_*` sont tous faux. Un modèle de départ entraîné sur ce fichier lit la réponse : ROC-AUC = 1,000 dans
   le notebook. Pour prédire les départs proprement, il faut reconstruire les variables *avant* la sortie.
2. **12 anomalies hypothécaires.** Pour ces propriétaires, la mensualité vaut toute la dette restante. Ils paient donc
   jusqu'à 280 000 CHF par mois et ont des découverts de plusieurs millions. C'est un défaut de la simulation :
   exclure les lignes où `mortgage_monthly_chf / mortgage_outstanding_chf > 0,5`.
3. **1 310 clients sans aucune transaction** (1 179 mineurs, 125 autres adultes, 6 nouveaux clients) : tous leurs
   flux sont vides. C'est un « pas d'activité », pas un zéro.
4. **Des règles de simulation très nettes.** Personne n'a de 3a avant 25 ans, et presque tous les actifs présents
   depuis le début en ont un. Un modèle de propension au 3a atteint donc 0,99 de ROC-AUC sans rien apprendre d'utile.
   Côté départs, `risk_appetite` porte à elle seule tout le signal : 0,858 avec elle, 0,521 sans elle (le hasard).
   Est-ce une cause, ou un attribut mis à jour au moment du départ ? C'est une question pour les organisateurs.
5. **Les soldes totaux contiennent le 3a.** Pour prédire la détention du 3a, retirer `balance_total_chf` et
   `min_monthly_total_balance_chf`, sinon le modèle triche.
6. **`sector` est figé**, et vide pour les clients arrivés en cours de route : préférer `employer_sector`.
   `tenure_months` est plafonnée à 12.
7. **Les négatifs sont réels.** 311 comptes courants sont dans le rouge, dont 13 sous −100 000 CHF, et 12 de ces
   13 cas sont les anomalies hypothécaires du point 2.

## Ce que ce fichier permet déjà (résultats du notebook)

- **Segmentation** (K-means, 4 groupes sur la population active) : retraités à forte part de dépenses de santé,
  jeunes actifs orientés sorties, restaurants et vêtements, petit groupe de jeunes sans revenu souvent à découvert,
  actifs établis de 46 ans en médiane qui détiennent presque tous un 3a.
- **Look-alike** : les 200 plus proches voisins d'un client. Sur l'exemple du plus gros portefeuille
  d'investissement, 177 des 200 sosies n'ont pas encore de compte d'investissement : des candidats directs pour une
  offre de conseil.
- **Propension au compte d'investissement** : ROC-AUC 0,833 pour un taux de base de 3,4 %. C'est la cible la plus
  réaliste du fichier.
- **Détection d'anomalies** (Isolation Forest, sans supervision) : les 11 anomalies hypothécaires présentes dans la
  population sont toutes parmi les 50 clients les plus atypiques.
- Le notebook exporte `nba_scores.parquet` (segment, propensions, anomalie, départ), une ligne par client.

## Ce que ce fichier ne contient pas

- **Aucune note de rendez-vous** : `interaction.csv` est vide dans les données fournies.
- **Aucun texte** : les motifs de départ et d'arrivée (en allemand) restent dans les données brutes.
- **Aucun détail de transaction** : commerçants, codes MCC, dates exactes. Ils sont dans `event.csv`
  (2,3 M de lignes), à exploiter pour des modèles plus fins.
- **Aucun historique mensuel** des variables : c'est une photographie à la période 24301.
