# Moteur de rotation des cultures · JAMM AGRI-TECH (Field Shift Sénégal)

Le moteur propose, pour chaque site (Thiès, Kaolack, Ziguinchor, Richard-Toll), les meilleures **rotations de cultures sur 3 ans**.
Il combine trois sources préparées par l'équipe :
- la **base agronomique des cultures** (`data/cultures_sahel_parametres_verifie.xlsx`) : règles, seuils, matrice de rotation, zones ;
- le **tableau des variétés réelles** (`data/besoins_cultures_varietes.csv`) : 47 variétés nommées (arachide, niébé, mil, sorgho, maïs), cycles et isohyètes sourcés ;
- 20 ans de climat (NASA POWER 2005-2024) et les sols (SoilGrids).

**Version définitive pour le projet Field Shift (v4, 15 novembre 2026)**. C'est la version de référence de l'équipe JAMM AGRI-TECH ; les résultats restent préliminaires tant que les paramètres agronomiques ne sont pas validés par un agronome.

**Version 4 (15 novembre 2026)** : intègre les données d'Issa de deux façons. (1) Son catalogue de variétés réelles (`data/besoins_cultures_varietes.csv`) est utilisé pour choisir les variétés. (2) Sa classification des années (`data/issa/dataset_site_annee.csv` : favorable, moyenne, défavorable) sert à **évaluer** le moteur : nouveaux onglets `Evaluation` et `Evaluation_detail`. Ajout de la colonne « Cultures sans données variétales » dans `Rotations`.

**Version 3 (15 novembre 2026)** : ajout du critère « Variétés documentées » (5 % du score) : part des cultures de la rotation qui ont des variétés réelles sourcées ; le poids des successions passe de 10 % à 5 %. Il départage les rotations à égalité sans sacrifier la fiabilité.

**Version 2 (14 novembre 2026)** : les variétés génériques « hâtive / tardive » sont remplacées par les variétés réelles pour l'arachide, le niébé, le mil, le sorgho et le maïs ; ajout du filtre par isohyète et de l'onglet `Varietes_zone_pluie`.

## Application (démo)

L'interface est **en anglais** (obligatoire pour Space Apps : page projet et documents liés en anglais). Les cultures gardent leur nom local avec la traduction anglaise entre parenthèses ; le SMS reste en français, avec sa traduction anglaise affichée pour le jury. La carte du Sénégal fonctionne sans internet (frontières incluses dans `data/afrique_ouest.geojson`, Natural Earth) ; seul le fond satellite des parcelles demande internet.

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans le navigateur. Le premier lancement prend environ 15 secondes (calcul des rotations), ensuite tout est instantané.

- **Panneau de gauche** : la localité et **les priorités de l'agriculteur** (Équilibré, Sécurité, Fertilité du sol, Production), les cultures voulues et les cultures refusées. Le classement des rotations se recalcule aussitôt.
- **Ma ferme** : 3 parcelles simulées sur image satellite, colorées par culture ; le curseur « Saison » fait tourner la rotation ; plan sur 6 saisons.
- **Début des pluies** : on choisit la date d'installation des pluies ; l'outil donne la variété à semer sur chaque parcelle, la chance de boucler le cycle, et le SMS en français.
- **Rejouer une année** : une saison passée (2005-2024) avec les pluies NASA, l'agriculteur seul contre l'agriculteur conseillé.
- **Preuve sur 20 ans** : l'évaluation avec les classes d'années d'Issa.
- **Données NASA** : les sources et leur rôle.

Les priorités de l'agriculteur ne sont pas dans le fichier Excel : ce sont des réponses de l'utilisateur. Le moteur les reçoit (fonction `classer` et profils `PROFILS` dans `rotation.py`).
Le fond satellite (Esri World Imagery) demande une connexion internet ; les parcelles sont simulées, leur emplacement est illustratif.

## Lancer

```bash
pip install pandas numpy openpyxl
python lancer_rotation.py
```

Le résumé s'affiche à l'écran et les résultats complets sont écrits dans **`resultats_rotation.xlsx`** (environ 10 secondes).

Options : `--excel chemin/vers/base.xlsx` (utiliser une autre version de la base), `--sortie mon_fichier.xlsx`, `--top 10`.

## Ce que fait le moteur, étape par étape

1. **Lecture de la base Excel** : seuils par culture, matrice de rotation, zones agroclimatiques, règles.
   La structure est vérifiée au démarrage : si un onglet ou une colonne a été renommé, le moteur s'arrête et dit lequel.
2. **Filtrage des cultures par site**, avec les règles de la base :
   - **R03** : pluie de l'année sèche (20 % des années les plus sèches) inférieure à la pluie minimale viable, culture exclue ;
   - **R09** : pH du sol (SoilGrids) hors de la plage tolérée, culture exclue ; **R10** : hors optimum, amendement conseillé ;
   - **R04** : pluie moyenne au-dessus du maximum toléré, alerte ;
   - zone agroclimatique : culture « à risque » dans la zone, pénalisée.
3. **Les variétés** :
   - arachide, niébé, mil, sorgho, maïs : les **variétés réelles** du tableau, avec leur cycle maximal (par prudence) ; le besoin en eau est interpolé entre les besoins min et max de la culture ;
   - **filtre isohyète** : une variété est écartée si la pluie annuelle médiane du site sort de sa plage d'isohyètes (tolérance 10 %) ; une culture sans aucune variété compatible est exclue du site ;
   - autres cultures (fonio, sésame, riz…) : deux variétés génériques, hâtive (cycle minimal) et tardive (cycle maximal) de la base.
4. **Test de chaque variété sur chaque saison 2005-2024**, semée au début réel des pluies. Elle réussit si :
   - elle mûrit avant la fin des pluies + la réserve en eau du sol (8 à 15 jours selon le site) ;
   - la pluie de la période + la réserve du sol couvrent au moins 80 % de son besoin en eau ;
   - pas de séquence sèche trop longue à la floraison (**R12**) ;
   - moins de 3 jours au-dessus de sa température critique à la floraison (**R13**).
5. **Choix de la variété au début des pluies** : la plus longue (donc la plus productive) qui a bouclé son cycle dans au moins 80 % des autres saisons.
   Si la culture prévue est trop risquée, elle est **remplacée par une culture de la même famille** compatible avec le précédent.
6. **Toutes les rotations de 3 ans** qui respectent la matrice de rotation (**R07**, pas de case 0) et le délai de retour (**R08**)
   sont rejouées sur les 18 fenêtres de 3 années consécutives, puis notées :

| Critère | Poids | Signification |
|---|---|---|
| Cycles réussis | 30 % | Part des cultures qui bouclent leur cycle |
| Pires années | 20 % | Réussite moyenne dans les 20 % de fenêtres les plus difficiles |
| Adaptation à la zone | 15 % | Cultures citées comme adaptées (+) ou à risque (−) dans la zone |
| Bilan azote | 15 % | Légumineuses fixatrices (+), céréales exportatrices (−) |
| Potentiel exploité | 10 % | Durée du cycle choisi par rapport au cycle maximal de la culture |
| Successions | 5 % | Note moyenne de la matrice de rotation (2 = recommandé) |
| Variétés documentées | 5 % | Part des cultures qui ont des variétés réelles sourcées (arachide, niébé, mil, sorgho, maïs) |

## Le fichier de résultats

| Onglet | Contenu |
|---|---|
| `Rotations` | Les meilleures rotations par site, avec le détail du score |
| `Revision_debut_saison` | La meilleure rotation rejouée année par année : début des pluies, variété retenue, remplacement éventuel, résultat réel |
| `Reussite_varietes` | Taux de réussite 2005-2024 de chaque variété, et sa cause d'échec la plus fréquente |
| `Regles_par_site` | Cultures autorisées ou exclues, et les règles déclenchées |
| `Varietes_zone_pluie` | Pour chaque variété : compatible ou non avec la pluie du site (isohyètes), et la portée de sa source |
| `Hypotheses` | Paramètres du moteur et réserve en eau du sol par site |

## Premiers résultats (version 3, base non encore validée)

- **Thiès** : niébé et mil, avec fonio, sorgho ou sésame. 98 à 100 % des cycles réussis.
- **Kaolack** : sésame, fonio, niébé ou arachide, 100 % des cycles réussis. Les rotations avec arachide (Fonio → Sésame → Arachide) sont à égalité avec la première (score 0,88). Les rotations 100 % documentées (mil, niébé, sorgho, arachide) descendent à 96 % de réussite, car le mil réel le plus court du tableau fait 105 jours.
- **Ziguinchor** : sorgho, maïs, arachide (98 %). Le mil est exclu : aucune variété du tableau n'est adaptée à 1 500 mm de pluie.
- **Richard-Toll** : environ 20 % de cycles réussis seulement. L'agriculture pluviale n'y est pas viable sans irrigation.

**À retenir** : les 5 premières rotations d'un site ont des scores très proches. Il faut les présenter comme un groupe de rotations recommandées.

## Évaluation par type d'année (onglet `Evaluation`)

Pour chaque culture à variétés réelles autorisée sur le site (Thiès, Kaolack, Ziguinchor ; Richard-Toll exclu car le pluvial n'y est pas viable), on rejoue 2005-2024 avec deux agriculteurs :
- **fixe** : sème toujours la variété la plus longue qui a réussi au moins 80 % des autres années ;
- **conseillé** : suit le moteur, qui choisit la variété au vu de la date de démarrage des pluies.

Chaque année est jugée sans que le moteur la connaisse (calcul sur les 19 autres années). Les années sont classées par Issa, indépendamment du moteur.
La classification d'Issa sert uniquement à l'évaluation : elle n'est connue qu'après la saison, elle n'entre pas dans la décision.

Résultat actuel : 30 échecs pour l'agriculteur fixe, 22 pour l'agriculteur conseillé, sur 200 décisions ; dans les années défavorables, 24 contre 18 sur 70. Les variétés semées sont en moyenne 6 jours plus longues (111 j contre 105 j).

## Modifier la base agronomique

Corrigez directement le fichier Excel, en gardant **exactement les mêmes noms d'onglets et de colonnes**, puis relancez `python lancer_rotation.py`.

## Hypothèses à valider (dans `rotation.py`, dictionnaire `HYPOTHESES`)

- **Tolérance aux séquences sèches** : la base ne donne qu'un niveau qualitatif. Il est converti en jours :
  très élevée 14, élevée 12, moyenne 10, faible à moyenne 9, faible 8 ; plafonné à 10 jours pour les cultures citées dans R12.
- **Cultures écartées** de la rotation pluviale : manioc (cycle de 8 à 18 mois), patate douce (irrigation d'appoint), oignon (contre-saison irriguée).
- **Zone de chaque site** : Thiès et Kaolack en sahélo-soudanienne, Ziguinchor en sub-guinéenne, Richard-Toll en sahélienne.
- **Poids du score**, seuil de confiance de 80 %, part du besoin en eau à couvrir (80 %).
- La règle de début de saison est celle qui reproduit exactement le fichier `climat_annuel.csv` (20 mm en 3 jours, sans 7 jours secs dans les 30 jours suivants).
  Elle diffère légèrement de R01 de la base (20 jours).

## Limites

- Le critère de réussite est **climatique** (la culture a-t-elle eu le temps et l'eau pour boucler son cycle ?), pas un rendement.
- La plupart des valeurs de la base sont marquées « non vérifiées » : elles doivent être validées avec l'ISRA avant tout usage réel.
- Sols : estimations SoilGrids à 250 m, pas des analyses de terrain.

## Fichiers

- `lancer_rotation.py` : script à lancer.
- `rotation.py` : le moteur de rotation (règles, scores, révision au début des pluies).
- `core.py` : détection du début et de la fin de la saison des pluies.
- `soil.py` : propriétés du sol et réserve en eau.
- `data/` : base agronomique Excel, tableau des variétés réelles, climat NASA POWER (4 sites), variables complémentaires et sols SoilGrids.

## Historique des versions
- **v1** : base agronomique de Cathy, variétés génériques (hâtive / tardive).
- **v2** : ajout des 47 variétés réelles et du filtre par isohyète.
