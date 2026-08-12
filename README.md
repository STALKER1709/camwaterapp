# CAMWATER — Extraction automatique de factures

Application complète permettant à plusieurs postes d'envoyer des photos ou scans
de factures d'eau CAMWATER, et d'alimenter automatiquement un **fichier Excel
général** avec les données extraites, contrôlées et ventilées par ministère.

L'OCR classique (Tesseract, easyocr, `pdftotext`) échoue sur ces documents : le
watermark circulaire bleu recouvre le texte et les scans n'ont pas de couche
texte fiable. La lecture est donc confiée à un modèle **Claude** en vision, avec
un schéma de sortie JSON imposé. Le modèle **transcrit**, il ne calcule jamais :
toute l'arithmétique, le mapping ministère et les contrôles sont faits en
Python, ce qui rend les résultats vérifiables et reproductibles.

---

## 1. Démarrage en une commande

### Linux / macOS (bash, zsh)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

### Windows — le plus simple : `demarrer.bat`

**Double-cliquez sur `demarrer.bat`** à la racine du projet. Le script enchaîne
tout seul : détection de Python, création du venv, installation des
dépendances, demande de la clé API si elle manque (enregistrée dans `.env`),
puis démarrage du serveur. Rien à taper, aucune syntaxe de shell à connaître.

Depuis PowerShell, si vous préférez :

```powershell
.\demarrer.bat            # démarrage normal
.\demarrer.bat -Tests     # vérifie l'installation via les 161 tests, sans clé API
```

Le `.bat` appelle `demarrer.ps1` avec `-ExecutionPolicy Bypass`, ce qui évite le
blocage « l'exécution de scripts est désactivée sur ce système ». Les
dépendances ne sont réinstallées que si `requirements.txt` a changé, donc les
démarrages suivants sont immédiats.

Les sections ci-dessous décrivent la procédure manuelle équivalente.

### Windows — prérequis : Python

**Commencez par vérifier si Python est déjà présent**, avant toute
installation. `py` est le lanceur officiel Windows : il trouve l'interpréteur
même quand la commande `python` reste captée par l'alias du Microsoft Store.

```powershell
py --version        # Python 3.10 ou supérieur convient
```

Si une version s'affiche, **passez directement à la section suivante** : rien à
installer, et utilisez `py` plutôt que `python` dans toutes les commandes.

Si `py` est introuvable, ou si `python` répond *« Python est introuvable ;
exécutez sans arguments à installer à partir du Microsoft Store »* (c'est
l'**alias d'exécution** de Windows : un raccourci vide vers le Store, pas un
interpréteur), installez alors le vrai Python :

```powershell
winget install --id Python.Python.3.12 -e
```

Puis **fermez et rouvrez PowerShell** (le PATH n'est rechargé qu'au démarrage
d'un nouveau terminal). Sans `winget` : installeur sur
<https://www.python.org/downloads/windows/>, en **cochant « Add python.exe to
PATH »** sur le premier écran.

Si `python` continue d'ouvrir le Store : **Paramètres → Applications →
Paramètres avancés des applications → Alias d'exécution d'application**,
désactivez `python.exe` et `python3.exe`.

> **Dépannage de l'installeur** — un échec `winget` du type
> *« Échec du programme d'installation avec le code de sortie : 2147942512 »*
> se décode en hexadécimal : `0x80070070`, soit l'erreur Win32 112,
> **ERROR_DISK_FULL**. Le venv et ses dépendances occupent 300 à 500 Mo ;
> vérifiez l'espace libre avec `Get-PSDrive C | Select-Object Used, Free`.

⚠️ Placez-vous **dans le dossier du dépôt** avant de créer le venv — jamais
dans `C:\WINDOWS\system32`, où l'écriture est refusée :

```powershell
cd $HOME\camwaterapp        # ou le chemin réel du dépôt cloné
```

### Windows — PowerShell

⚠️ **Ne recopiez pas les commandes bash ci-dessus dans PowerShell** : `&&`,
`source` et `export` n'y existent pas (« Le jeton `&&` n'est pas un séparateur
d'instruction valide »). Utilisez ces quatre lignes, une par une :

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python app.py
```

Si PowerShell refuse d'exécuter `Activate.ps1` (« l'exécution de scripts est
désactivée sur ce système »), deux solutions :

```powershell
# soit autoriser les scripts pour cette session uniquement
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

# soit se passer complètement de l'activation (méthode la plus robuste)
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\venv\Scripts\python.exe app.py
```

Séquence complète recommandée sous Windows, avec `py` et le Python du venv en
chemin direct — elle évite d'un coup l'alias du Store et la stratégie
d'exécution :

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\venv\Scripts\python.exe app.py
```

Contrôle de l'installation **sans clé API** (les 161 tests simulent la lecture
visuelle) :

```powershell
.\venv\Scripts\python.exe -m pytest tests\ -q
```

Pour rendre la clé permanente (au lieu de la retaper à chaque session) :

```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."     # effectif dans les NOUVEAUX terminaux
```

### Windows — invite de commandes (cmd.exe)

```bat
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

Puis ouvrez **<http://localhost:8000/>** et déposez vos factures.

> **Deux points d'attention sous Windows**
> * Le classeur ne peut pas être remplacé s'il est **ouvert dans Excel** : le
>   traitement s'arrête proprement avec un message explicite et le fichier reste
>   intact — fermez Excel puis relancez.
> * Les journaux sont forcés en UTF-8 : les symboles `≠`, `→`, `−` des messages
>   d'anomalie s'affichent correctement même quand la sortie est redirigée vers
>   un fichier ou un service Windows.

> **Dépendance système recommandée** — `poppler-utils` fournit `pdftoppm`, utilisé
> pour convertir les PDF en PNG haute définition (300 DPI par défaut).
> Ubuntu/Debian : `sudo apt install poppler-utils` · macOS : `brew install poppler`
> · Windows : télécharger poppler et ajouter son dossier `bin` au `PATH`.
> **S'il est absent, l'application ne s'arrête pas** : elle transmet le PDF
> nativement au modèle et le signale dans les journaux. La conversion en PNG
> donne toutefois de meilleurs résultats sur les scans dégradés.

---

## 2. Arborescence du projet

```
camwaterapp/
├── app.py                      # point d'entrée : python app.py
├── demarrer.bat                # Windows : double-clic, tout s'enchaîne
├── demarrer.ps1                # script appelé par demarrer.bat
├── requirements.txt
├── README.md
├── .env.example                # modèle de configuration (à copier en .env)
├── .gitignore
│
├── camwater/                   # code applicatif
│   ├── __init__.py
│   ├── config.py               # constantes, chemins, variables d'environnement
│   ├── logging_setup.py        # journaux console + logs/app.log (rotatifs)
│   ├── models.py               # LigneFacture, RapportTraitement
│   ├── api.py                  # endpoints FastAPI + page d'upload
│   ├── pipeline.py             # orchestration du traitement d'une facture
│   ├── extraction.py           # prompt interne + appel vision au modèle
│   ├── pdf_utils.py            # conversion PDF → PNG (300 DPI)
│   ├── image_utils.py          # résolution utile + atténuation du tampon
│   ├── calculs.py              # parsing des nombres + formules de facturation
│   ├── periodes.py             # périodes « mars-2026 » et mois manquants
│   ├── mapping.py              # règles d'affectation du ministère
│   ├── validation.py           # contrôles de cohérence + rapports d'erreur
│   ├── excel_manager.py        # écriture transactionnelle du classeur
│   └── watcher.py              # mode « dossier partagé » (sans frontend)
│
├── static/
│   └── index.html              # interface web (aucun build, aucune dépendance)
│
├── tools/
│   ├── generer_exemple_excel.py  # produit un classeur d'exemple sans appel API
│   └── apercu_pretraitement.py   # compare une facture avant/après préparation
│
├── docs/
│   └── exemple_CAMWATER_Pointage_General.xlsx   # exemple de livrable
│
├── tests/                      # 161 tests, exécutables sans clé API
│
├── data/
│   ├── uploads/                # factures reçues (zone de travail)
│   ├── inbox/                  # dossier surveillé (mode dossier partagé)
│   ├── processed/              # factures traitées avec succès
│   ├── errors/                 # factures en échec
│   ├── reports/                # un rapport JSON par facture
│   └── output/
│       └── CAMWATER_Pointage_General.xlsx   # ← LE FICHIER EXCEL GÉNÉRAL
│
└── logs/
    └── app.log                 # journal applicatif (rotation 5 × 5 Mo)
```

---

## 3. Envoyer des factures

### 3.1 Interface web (recommandé pour plusieurs postes)

<http://localhost:8000/> — glisser-déposer ou sélection multiple. Trois champs
facultatifs :

| Champ | Rôle |
|---|---|
| **Année** | Utilisée si l'année de la période est illisible sur la facture |
| **Administration** | Ministère de repli si aucun pattern de mapping ne correspond |
| **Poste / agent** | Tracé dans l'onglet `Journal` du classeur |

L'écran affiche, pour chaque facture : nombre de lignes écrites, lignes
conformes, lignes à vérifier, lignes illisibles, et le détail des anomalies.

### 3.2 API (intégration, script, autre logiciel)

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "fichiers=@facture-mars-2026.pdf" \
  -F "fichiers=@facture-avril-2026.pdf" \
  -F "annee=2026" \
  -F "administration=MINSANTE" \
  -F "utilisateur=poste-3"
```

| Endpoint | Rôle |
|---|---|
| `GET /` | Page d'upload |
| `GET /health` | Sonde de disponibilité (version, modèle, mode PDF) |
| `POST /api/upload` | Dépôt d'une ou plusieurs factures |
| `GET /api/stats` | État du classeur (feuilles, lignes, factures traitées) |
| `GET /api/excel` | Téléchargement du fichier Excel général |
| `GET /api/rapports` | Liste des rapports de traitement |
| `GET /api/rapports/{nom}` | Contenu d'un rapport JSON |
| `GET /docs` | Documentation interactive (OpenAPI) |

### 3.3 Dossier partagé (sans frontend)

Chaque poste dépose ses scans sur un partage réseau ; un service les intègre :

```bash
python -m camwater.watcher --dossier /mnt/partage/factures --intervalle 10
python -m camwater.watcher --une-passe        # traiter puis quitter (cron)
```

Un fichier n'est pris en compte que lorsque sa taille est stable entre deux
scrutations, ce qui évite de traiter une copie réseau encore en cours.

---

## 4. Le fichier Excel général

**Emplacement :** `data/output/CAMWATER_Pointage_General.xlsx`
(configurable via `CAMWATER_EXCEL_FILENAME` et `CAMWATER_OUTPUT_DIR`).
Il s'ouvre avec Excel, LibreOffice Calc ou Google Sheets, ou se télécharge
depuis l'interface web (bouton « Télécharger l'Excel général »).

Un exemple complet et représentatif est fourni :
**`docs/exemple_CAMWATER_Pointage_General.xlsx`**, régénérable à tout moment
sans clé API :

```bash
python tools/generer_exemple_excel.py
```

### 4.1 Feuilles du classeur

| Feuille | Contenu |
|---|---|
| `Résumé` | Totaux par **administration × période** : état, nb lignes, consommation, HT, TVA, TTC, lignes à vérifier, lignes illisibles, plus une ligne `TOTAL GÉNÉRAL`. **Les mois sans facture y figurent** avec l'état `MANQUANTE` (voir §4.3). Reconstruite intégralement à chaque écriture. |
| *une feuille par ministère* (`MINSANTE`, `MINESEC`, `DGSN`, …) | Les lignes de facturation, 17 colonnes standard + 3 colonnes techniques |
| `Anomalies` | Une ligne par anomalie : fichier source, feuille, statut, compte client, code abonnement, nom abonné, description |
| `Lignes écartées` | Les lignes **sans numéro de compte client**, nulles pour le pointage (voir §5.5). Conservées avec leurs 17 colonnes pour contrôle, mais exclues des feuilles par ministère et de tous les totaux |
| `Journal` | Une ligne par facture intégrée : horodatage, fichier, **empreinte SHA-256**, utilisateur, **compte client**, **période**, pages, lignes écrites/à vérifier/illisibles/écartées, confiance de lecture |

Pour une **feuille unique** avec une colonne « Administration » plutôt qu'une
feuille par ministère, définir `CAMWATER_FEUILLE_UNIQUE=Pointage` : la colonne
`Ministère_2026` joue alors ce rôle.

### 4.2 Les 17 colonnes standard

| # | Colonne | Type |
|---|---|---|
| 1 | DR | Texte |
| 2 | Agence | Texte (code à 4 chiffres) |
| 3 | Période | Texte `MMM-AAAA` (ex. `mars-2026`) |
| 4 | Compte client | Texte |
| 5 | Nom du client | Texte |
| 6 | Ville | Texte |
| 7 | Code abonnement (PL) | Texte |
| 8 | Nom abonné | Texte |
| 9 | N° compteur | Texte |
| 10 | Index nouvel | Nombre |
| 11 | Index ancien | Nombre |
| 12 | Consommation | Nombre |
| 13 | Location compteur | Nombre |
| 14 | TVA | Nombre |
| 15 | Montant HT | Nombre |
| 16 | Ministère_2026 | Texte |
| 17 | Montant TTC | Nombre |

Trois colonnes techniques suivent, pour l'audit : **Statut**
(`OK` / `À_VÉRIFIER` / `ILLISIBLE` / `ÉCARTÉE`), **Fichier source**, **Anomalies**.
Les lignes à vérifier sont surlignées en jaune, les illisibles en orange, les
écartées en gris.

### 4.3 Les mois sans facture apparaissent au Résumé

Un mois pour lequel aucune facture n'est arrivée serait invisible : il
n'existerait tout simplement aucune ligne. Le Résumé le fait donc apparaître
explicitement, sur fond rosé, avec l'état `MANQUANTE` et des totaux à zéro.

Deux manques distincts sont couverts :

* **un trou de calendrier** — janvier et mars pointés, février absent partout ;
* **une administration absente sur un mois** couvert par une autre — MINSANTE
  reçue en février, MINESEC non.

L'étendue de référence va de la plus ancienne à la plus récente période présente
dans le classeur : le Résumé répond ainsi directement à la question « quelles
factures nous manque-t-il ? ». Les lignes `MANQUANTE` portent des zéros et
n'entrent donc dans aucun total. Désactivable par `CAMWATER_COMPLETER_MOIS=false`.

---

## 5. Règles métier appliquées

### 5.1 Formules (`camwater/calculs.py`)

```
Montant consommation = Consommation × 382
Montant HT           = Montant consommation + Location compteur
TVA                  = ARRONDI(Montant HT × 0,1925)      # arrondi commercial
Montant TTC          = Montant HT + TVA
```

Constantes surchargeables : `CAMWATER_PRIX_UNITAIRE`, `CAMWATER_TAUX_TVA`.

### 5.2 Lecture des nombres — aucun chiffre perdu

Les calculs utilisent `Decimal` (jamais `float`) : pas d'erreur d'arrondi
binaire sur les montants. Le parsing suit des règles explicites :

| Écrit sur la facture | Interprété |
|---|---|
| `1.234,56` | `1234.56` (virgule = séparateur décimal) |
| `1,234.56` | `1234.56` (le dernier séparateur est le décimal) |
| `1 234`, `12 500 FCFA` | `1234`, `12500` (espaces et devise retirés) |
| `1.234` | `1234` (groupes de 3 chiffres = milliers) |
| `12.5` | `12.5` (pas un groupe de milliers → décimal) |
| `(250)` | `-250` |
| `ILLISIBLE`, `""`, `-`, `néant` | valeur absente |

### 5.3 Reconstruction des valeurs manquantes

Une valeur illisible mais **déductible** est reconstruite puis marquée comme
dérivée (visible dans la colonne `Anomalies` et dans le rapport JSON) :

* `Consommation` ← `Index nouvel − Index ancien`, ou ← `(HT − Location) / 382`
  (uniquement si le résultat est un entier exact) ;
* `Montant HT` ← `Consommation × 382 + Location`, ou ← `TTC − TVA` ;
* `TVA` ← `ARRONDI(HT × 0,1925)` ;
* `Montant TTC` ← `HT + TVA` ;
* `Index nouvel` / `Index ancien` ← à partir de l'autre index et de la consommation.

Une valeur non reconstructible n'est **jamais devinée** : la cellule porte
`ILLISIBLE` et la ligne est signalée.

### 5.4 Mapping ministère (`camwater/mapping.py`)

1. **Exclusions** — entités publiques non gouvernementales (CRTV, BEAC,
   CAMRAIL, CAMTEL, ENEO, SONARA, CNPS, ART, CDC…) → `HORS_PERIMETRE`.
2. **Patterns priorisés** — le `Nom abonné` est examiné en premier sur toute la
   liste de priorités, car il désigne l'entité réellement desservie ; le
   `Nom du client` (titulaire du compte, souvent le ministère payeur) ne sert
   qu'en second recours. Sans cela, un lycée facturé sur un compte MINSANTE
   serait rattaché à la santé.
   Priorité 1 (institutions : PRC, GP, SPM, AN, SENAT) → 3 (DGSN, MINDEF,
   MINJUSTICE) → 4 (MINAT) → 5 (MINSANTE) → 6 (éducation) → 7 (MINFI) → …
   Les libellés fonctionnels sont reconnus, pas seulement les sigles :
   *hôpital*, *lycée*, *commissariat*, *préfecture*, *tribunal*, *centre des
   impôts*…
3. **Repli** — administration saisie à l'upload si fournie, sinon `À_VÉRIFIER`.

**Extension sans toucher au code** — un fichier JSON pointé par
`CAMWATER_MAPPING_FILE` :

```json
{
  "regles": [
    {"code": "MINSANTE", "priorite": 5, "patterns": ["CENTRE MEDICO SOCIAL"]}
  ],
  "exclusions": ["MA SOCIETE SA"]
}
```

### 5.5 Contrôles — « zéro erreur tolérée »

Aucune ligne n'est écartée en silence. Chaque ligne reçoit un statut :

| Statut | Signification |
|---|---|
| `OK` | Colonnes obligatoires présentes, arithmétique cohérente, ministère identifié |
| `À_VÉRIFIER` | Écrite mais signalée : écart de total, TVA incohérente, index contradictoires, ministère indéterminé, entité hors périmètre |
| `ILLISIBLE` | Une donnée obligatoire est absente et non reconstructible |
| `ÉCARTÉE` | **Ligne nulle, faute de numéro de compte client.** Exclue du pointage et de tous les totaux, rangée dans la feuille `Lignes écartées` — jamais supprimée |

**La règle du numéro de compte prime sur tous les autres contrôles.** Sans
compte client, une ligne n'est rattachable à aucun abonné : elle est donc nulle,
et les contrôles arithmétiques ou de mapping n'ont plus de sens. Le compte est
lu **au niveau de la ligne** lorsque le tableau en porte un (factures
récapitulatives multi-comptes), sinon repris de l'en-tête. Une colonne compte
présente mais indéchiffrable écarte **cette seule ligne**, pas la facture.

Contrôles effectués : colonnes obligatoires, `HT + TVA = TTC`,
`TVA = ARRONDI(HT × 0,1925)`, `Index nouvel − Index ancien = Consommation`,
consommation non négative, cohérence du ministère, et **comparaison des sommes
de lignes aux totaux imprimés en pied de facture**. Un écart de total marque
toute la facture à vérifier — aucun montant douteux ne passe inaperçu.

Chaque facture produit un rapport JSON dans `data/reports/` (statistiques,
totaux lus vs recalculés, anomalies, détail ligne à ligne).

### 5.6 Intégrité du fichier Excel

* **Atomicité** — le classeur est écrit dans un fichier temporaire du même
  dossier puis basculé par `os.replace()`. Une coupure en cours d'écriture
  laisse l'ancien fichier intact : jamais de ligne à moitié écrite. Une copie de
  secours `.xlsx.bak` est conservée.
* **Concurrence** — un verrou fichier (`filelock`) sérialise les écritures
  venant de plusieurs postes ou requêtes simultanées.
* **Doublons, à deux niveaux** — d'abord l'**empreinte SHA-256** du fichier,
  contrôlée *avant* tout appel au modèle : un fichier déjà intégré est refusé
  sans frais. Puis, après lecture, l'**identité métier** de la facture, à savoir
  le couple *(compte client, période)* : un re-scan, un recadrage ou un autre
  nom de fichier produisent une empreinte différente pour la **même** facture,
  que seul ce second contrôle peut voir. Les couples déjà présents sont relus
  dans les feuilles de données, qui font foi. Message renvoyé :
  *« Facture déjà présente dans le fichier général (compte 0012345678 sur
  mars-2026) »*. Désactivable avec `CAMWATER_REJETER_DOUBLONS=false`.

---

## 6. Lecture visuelle : prompt et qualité

### 6.1 Le prompt envoyé au modèle

Il est intégralement lisible dans **`camwater/extraction.py`**, constante
`PROMPT_EXTRACTION`. Points clés :

* le tampon circulaire bleu est décrit comme un artefact à traverser ;
* **chaque nombre est rendu en chaîne, exactement comme imprimé** — le modèle ne
  calcule rien, ne somme rien, n'arrondit rien ;
* un chiffre non déchiffrable devient `ILLISIBLE` plutôt qu'une valeur devinée
  (une valeur fausse est bien plus coûteuse qu'une valeur signalée) ;
* les confusions fréquentes sur ces scans sont explicitement nommées
  (`0/O`, `1/7`, `5/6`, `8/B`, `3/8`) ;
* les cas particuliers sont traités : page de garde, page de continuation sans
  en-tête, plusieurs blocs de lignes sur une page ;
* le modèle renvoie une **confiance** et des **remarques** exploitées par les
  rapports.

La réponse est contrainte par `output_config.format` (JSON Schema) : elle est
structurellement garantie, il n'y a jamais de JSON à « rattraper ». Sur un
document multi-pages, l'en-tête déjà lu est réinjecté en contexte pour les pages
de continuation, et les lignes de toutes les pages sont concaténées.

Les consignes, identiques d'une page à l'autre, sont placées dans le bloc
`system` avec `cache_control` : elles ne sont facturées plein tarif qu'à la
première page d'un lot, puis relues depuis le cache. L'image est placée **avant**
la question dans le tour utilisateur, ce qui donne au modèle la page entière
avant de savoir ce qu'on lui en demande.

### 6.2 Résolution utile de l'image

Le modèle exploite jusqu'à **2576 px** sur le grand côté ; au-delà, c'est le
service qui réduit l'image, avec un filtre que l'on ne maîtrise pas. Une A4
rendue à 200 DPI ne fait que 2338 px : environ 240 px de finesse étaient
inutilisés sur des chiffres déjà difficiles.

Le rendu se fait donc à **300 DPI** (3508 px), puis `camwater/image_utils.py`
réduit lui-même à 2576 px par filtre de Lanczos. Ce sur-échantillonnage moyenne
le bruit du scan et conserve mieux les traits fins qu'un rendu direct à la
taille cible. Le coût en jetons est identique : il ne dépend que de la taille
finale envoyée.

### 6.3 Atténuation du tampon bleu (optionnel)

`CAMWATER_ATTENUER_TAMPON=true` ne conserve que le **canal bleu** de l'image :
l'encre bleue réfléchit le bleu, elle y est presque aussi claire que le papier
et s'efface, tandis que le texte noir — sombre sur les trois canaux — reste
lisible. Sur une image de contrôle, le trait du tampon passe d'une clarté de 110
à 197 (le papier étant à 255) pendant que les chiffres tombent à 0 : l'écart
tampon/chiffres passe de 85 à 197.

L'effet dépend de la teinte réelle de **vos** tampons, d'où le réglage désactivé
par défaut. Jugez sur pièce avant d'activer :

```bash
python tools/apercu_pretraitement.py data/errors/MaFacture.pdf
```

L'outil écrit trois images dans `data/apercus/` (original, redimensionnée,
tampon atténué) à comparer côte à côte. Si l'atténuation dégrade quoi que ce
soit, laissez l'option à `false` — la réduction contrôlée de la 6.2 est déjà un
gain net.

### 6.4 Double lecture (optionnel)

Un modèle rapporte une valeur mal lue avec la même assurance qu'une valeur
juste : rien dans sa réponse ne distingue un `1284` erroné d'un `1234` correct.
`CAMWATER_DOUBLE_LECTURE=true` fait lire chaque page **deux fois de façon
indépendante** et confronte les deux transcriptions chiffre par chiffre.

La comparaison porte sur la **valeur**, pas sur l'écriture : « 15 280 » et
« 15.280 » concordent, « 15 280 » et « 15 285 » divergent. Toute divergence
marque la ligne `À_VÉRIFIER` avec les deux lectures citées dans l'anomalie ; un
découpage du tableau en nombres de lignes différents est signalé comme tel. Les
valeurs retenues sont celles de la lecture la plus confiante.

Le coût et la durée doublent : à réserver aux lots sensibles ou à une campagne
de contrôle, plutôt qu'au traitement courant.

---

## 7. Obtenir la clé API Anthropic

La lecture visuelle des factures passe par l'API Anthropic ; il faut donc une
clé. Elle se crée sur la console : <https://platform.claude.com>
(l'ancienne adresse `console.anthropic.com` y redirige).

1. Connectez-vous ou créez un compte ;
2. **Settings → API keys** (<https://platform.claude.com/settings/keys>) ;
3. **Create key**, avec un nom parlant (ex. `camwater-poste-serveur`) ;
4. **Copiez la clé tout de suite** : elle commence par `sk-ant-` et n'est
   affichée qu'une seule fois. Perdue, il faut en régénérer une.

Trois points à connaître avant de commencer :

* **Un abonnement Claude.ai ne donne pas accès à l'API.** Claude Pro ou Max
  couvre le site et les applications, pas l'API : c'est une facturation
  distincte. Créditez le compte dans **Settings → Billing**, sinon la clé
  existe mais chaque appel est rejeté.
* **Une seule clé suffit pour tous les postes.** Elle est installée sur la
  machine qui héberge l'application ; les autres postes passent par
  l'interface web et ne manipulent aucun secret.
* **Coût indicatif** — Claude Opus 5 est facturé 5 $ par million de jetons en
  entrée et 25 $ en sortie. Une page de facture scannée représente quelques
  milliers de jetons en entrée, plus la transcription JSON en sortie : comptez
  de quelques centimes à une dizaine de centimes par page, à confirmer sur vos
  propres factures (le volume de sortie suit le nombre de lignes d'abonnement).
  `CAMWATER_MODEL` et `CAMWATER_EFFORT` permettent d'ajuster, mais vérifiez la
  qualité de lecture avant de descendre en gamme : c'est la difficulté des
  scans tramés qui a justifié ce choix de modèle.

Où placer la clé, par ordre de commodité :

| Méthode | Portée |
|---|---|
| `demarrer.bat` la demande au premier lancement | Écrite dans `.env`, permanente, ignorée par git |
| `.env` à la racine : `ANTHROPIC_API_KEY=sk-ant-...` | Permanente |
| `$env:ANTHROPIC_API_KEY = "sk-ant-..."` (PowerShell) | Session courante uniquement |
| `setx ANTHROPIC_API_KEY "sk-ant-..."` (PowerShell) | Permanente, effective dans les **nouveaux** terminaux |

⚠️ Ne committez jamais la clé. `.env` figure dans `.gitignore` ; si une clé a
été exposée, révoquez-la depuis la console et créez-en une autre.

---

## 8. Configuration

Toutes les options sont des variables d'environnement, ou un fichier `.env`
(voir `.env.example`). Les plus utiles :

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Authentification du modèle (**requis**) |
| `CAMWATER_MODEL` | `claude-opus-5` | Modèle de lecture visuelle |
| `CAMWATER_EFFORT` | `high` | Profondeur d'analyse (`low` → `max`) |
| `CAMWATER_PORT` | `8000` | Port d'écoute |
| `CAMWATER_PDF_DPI` | `300` | Résolution de conversion PDF → PNG |
| `CAMWATER_COTE_LONG` | `2576` | Grand côté de l'image envoyée au modèle |
| `CAMWATER_DOUBLE_LECTURE` | `false` | Deux lectures confrontées (coût ×2) |
| `CAMWATER_ATTENUER_TAMPON` | `false` | Fait pâlir le tampon bleu avant lecture |
| `CAMWATER_MAX_UPLOAD_MB` | `50` | Taille maximale d'un fichier |
| `CAMWATER_PRIX_UNITAIRE` | `382` | Prix unitaire du m³ |
| `CAMWATER_TAUX_TVA` | `0.1925` | Taux de TVA |
| `CAMWATER_TOLERANCE` | `1` | Écart toléré (FCFA) sur les totaux |
| `CAMWATER_FEUILLE_UNIQUE` | *(vide)* | Feuille unique au lieu d'une par ministère |
| `CAMWATER_COMPLETER_MOIS` | `true` | Fait figurer les mois sans facture au Résumé |
| `CAMWATER_MAPPING_FILE` | *(vide)* | Règles de mapping supplémentaires |
| `CAMWATER_INBOX_DIR` | `data/inbox` | Dossier surveillé |

---

## 9. Tests

La suite complète tourne **sans clé API** (la lecture visuelle est simulée) :

```bash
python -m pytest tests/ -q      # 161 tests
```

Couverture : parsing des nombres et formules, dérivations, mapping ministère et
exclusions, normalisation des périodes, statuts de validation, contrôle des
totaux, écriture Excel (feuilles, résumé, anomalies, journal, doublons,
**atomicité en cas d'échec d'écriture**), endpoints HTTP, et le pipeline de bout
en bout (succès, doublon refusé, échec de lecture, écart de totaux).

Deux séries méritent un mot, parce qu'elles **mesurent** au lieu de faire
confiance au raisonnement :

* `test_image_utils.py` calcule la clarté moyenne de zones connues (tampon,
  chiffres, papier) avant et après traitement. C'est ce qui a révélé qu'une
  première version travaillait sur le canal rouge et **assombrissait** le tampon
  au lieu de l'effacer ; le test de régression le verrouille ;
* `test_double_lecture.py` vérifie que la confrontation compare des nombres et
  non leur écriture, qu'aucune ligne divergente n'échappe au marquage, et que la
  divergence ressort bien jusque dans la ligne du pointage.

---

## 10. Dépannage

| Symptôme | Cause et remède |
|---|---|
| `Python est introuvable ; exécutez sans arguments à installer à partir du Microsoft Store` | Python n'est pas installé : c'est l'alias d'exécution Windows. Voir « Windows — prérequis » au §1 |
| `Le jeton « && » n'est pas un séparateur d'instruction valide` | Commandes bash recopiées dans PowerShell — utilisez la section PowerShell du §1 |
| `.\venv\Scripts\Activate.ps1 n'est pas reconnu` | Le venv n'a pas été créé (Python absent), ou vous n'êtes pas dans le dossier du projet |
| `l'exécution de scripts est désactivée sur ce système` | Stratégie d'exécution PowerShell — utilisez `.\venv\Scripts\python.exe app.py` sans activer le venv |
| `Le crédit du compte API Anthropic est épuisé` | Achetez des crédits sur <https://platform.claude.com> → **Plans & Billing**. La clé est valide, seul le solde est en cause |
| `Aucune clé API n'est configurée` | Renseignez `ANTHROPIC_API_KEY` dans `.env` (voir §7), ou relancez `demarrer.bat` qui la demande |
| `La clé API est invalide ou a été révoquée` | Créez une nouvelle clé sur <https://platform.claude.com> → Settings → API keys |
| `… est verrouillé par une autre application` | Le classeur est ouvert dans Excel : fermez-le et relancez (aucune ligne n'a été écrite) |
| `poppler-utils absent` dans les journaux | Installez poppler pour la conversion en images ; sinon le PDF est lu nativement (dégradé mais fonctionnel) |
| `Impossible d'ouvrir … xlsx` | Le classeur est ouvert dans Excel : fermez-le. Une sauvegarde `.xlsx.bak` est disponible |
| `Facture déjà intégrée sous le nom …` | Contenu identique déjà traité (protection anti-doublon) ; `CAMWATER_REJETER_DOUBLONS=false` pour l'ignorer |
| `Réponse tronquée … augmentez CAMWATER_MAX_TOKENS` | Facture très longue : passez `CAMWATER_MAX_TOKENS` à 64000 |
| Beaucoup de lignes `À_VÉRIFIER` | Consultez l'onglet `Anomalies` et les rapports `data/reports/*.json` : la cause exacte y est écrite ligne par ligne |
| Ministère `À_VÉRIFIER` récurrent | Ajoutez un pattern via `CAMWATER_MAPPING_FILE`, ou renseignez le champ « Administration » à l'upload |

Les journaux détaillés sont dans `logs/app.log` (`CAMWATER_LOG_LEVEL=DEBUG`
pour plus de détail).
