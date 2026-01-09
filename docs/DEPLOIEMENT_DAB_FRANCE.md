# Guide de Deploiement DAB+ en France

Ce guide explique comment deployer une solution de diffusion DAB+ en France, que ce soit pour une diffusion locale/privee ou pour une integration avec les reseaux de diffusion nationaux.

## Table des matieres

1. [Infrastructure DAB+ en France](#infrastructure-dab-en-france)
2. [Architecture technique](#architecture-technique)
3. [Options de deploiement](#options-de-deploiement)
4. [Deploiement local (tests/prive)](#deploiement-local)
5. [Integration reseau national](#integration-reseau-national)
6. [Aspects reglementaires](#aspects-reglementaires)

---

## Infrastructure DAB+ en France

### Operateurs de diffusion

En France, deux diffuseurs majeurs operent l'infrastructure DAB+ :

| Operateur | Description | Couverture |
|-----------|-------------|------------|
| **TDF** | Diffuseur historique francais | 11 850 sites dans le monde, principaux points hauts (Tour Eiffel, Pic du Midi, Puy de Dome) |
| **towerCast** | Filiale du groupe NRJ | 500+ sites urbains et peri-urbains, multitechnologies |

### Organisation des multiplex

Les radios sont regroupees en **multiplex** (ensembles DAB+) :

| Multiplex | Type | Contenu |
|-----------|------|---------|
| **M1** | National metropolitain | Radios nationales publiques et privees |
| **M2** | National metropolitain | Radios nationales privees |
| **Multiplex locaux** | Regional/local | Radios locales et regionales |

**Capacite d'un multiplex :**
- 864 "unites de capacite" (CU)
- Debit total : ~1 184 kbit/s
- Jusqu'a 20 programmes radio par multiplex

---

## Architecture technique

### Schema de la chaine DAB+

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           CHAINE DE DIFFUSION DAB+                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐     ┌────────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│   Studios   │────▶│  Encodeurs │────▶│ Multiplexeur │────▶│ Reseau EDI/  │────▶│  Emetteurs │
│   Radio     │     │  HE-AAC v2 │     │   DAB+       │     │ ETI          │     │  DAB+ VHF  │
│             │     │            │     │              │     │              │     │  Bande III │
└─────────────┘     └────────────┘     └──────────────┘     └───────────────┘     └────────────┘
      │                   │                   │                    │                    │
      │                   │                   │                    │                    │
      ▼                   ▼                   ▼                    ▼                    ▼
   Source            Compression          Combinaison          Transport           Emission
   audio              audio               programmes           IP/FH/Sat          RF 174-240
                     32-128k                                                         MHz
```

### 1. Encodage audio (Studio)

L'audio est encode selon le standard DAB+ :

| Parametre | Specification |
|-----------|---------------|
| **Codec** | MPEG-4 HE-AAC v2 |
| **Debit typique** | 32-64 kbit/s stereo |
| **Parametric Stereo** | Oui (PS) |
| **Taux echantillonnage** | 48 kHz |

**Avec RadioLM :**
```bash
# Encodage d'un fichier pour DAB+
dab-streamer encode file audio.mp3 --codec he-aacv2 --bitrate 64
```

### 2. Multiplexage (Tete de reseau)

Le multiplexeur combine plusieurs programmes en un seul flux :

| Fonction | Description |
|----------|-------------|
| **Entrees** | Flux audio encodes de chaque radio |
| **Sortie** | Flux ETI/EDI horodate |
| **SFN** | Synchronisation pour reseau isofrecquence |
| **PAD** | Donnees associees (DLS, slideshow) |

**Configuration RadioLM pour multiplexage :**
```bash
# Generer la configuration ODR-DabMux
dab-streamer broadcast generate-config

# Structure du fichier dabmux.mux
# - Ensemble : identification du multiplex
# - Services : liste des radios
# - Subchannels : flux audio
# - Components : liaison service/subchannel
```

### 3. Transport/Contribution

Le signal multiplex est achemine vers les emetteurs :

| Methode | Usage | Avantages |
|---------|-------|-----------|
| **EDI sur IP** | Standard actuel | Flexible, economique |
| **Fibre optique** | Sites principaux | Haute fiabilite |
| **Faisceaux hertziens (FH)** | Sites isoles | Couverture etendue |
| **Satellite** | Distribution nationale | Couverture totale |

### 4. Emission RF

Les emetteurs diffusent en **Bande III VHF** :

| Parametre | Valeur |
|-----------|--------|
| **Bande** | III VHF |
| **Frequences** | 174-240 MHz |
| **Canaux** | 5A a 13F |
| **Modulation** | OFDM (COFDM) |
| **Mode** | Mode I (France) |

---

## Options de deploiement

### Option 1 : Diffusion locale/privee

Pour tests, demonstrations, ou couverture privee (entreprise, evenement).

**Materiel requis :**
- PC avec RadioLM
- SDR (LimeSDR, PlutoSDR, HackRF)
- Antenne accordee Bande III
- Licence experimentale (si puissance > quelques mW)

**Schema :**
```
┌──────────┐     ┌──────────┐     ┌─────────┐     ┌──────────┐
│ RadioLM  │────▶│ ODR-Mux  │────▶│ODR-Mod  │────▶│   SDR    │────▶ Antenne
│ (source) │     │          │     │         │     │ LimeSDR  │
└──────────┘     └──────────┘     └─────────┘     └──────────┘
```

### Option 2 : Integration operateur (TDF/towerCast)

Pour diffusion nationale ou regionale officielle.

**Processus :**
1. Obtenir autorisation CSA/ARCOM
2. Contacter TDF ou towerCast
3. Fournir flux audio encode (EDI/IP)
4. L'operateur gere multiplexage et emission

**Schema :**
```
┌──────────┐     ┌──────────┐                    ┌───────────────┐
│ RadioLM  │────▶│ Encodeur │────▶ Internet ────▶│ Multiplexeur  │────▶ Emetteurs
│ (studio) │     │ HE-AAC   │      (EDI/IP)      │ TDF/towerCast │     nationaux
└──────────┘     └──────────┘                    └───────────────┘
```

### Option 3 : Diffusion hybride (flotte vehicules)

Combinaison streaming IP + reception DAB+ eventuelle.

**Schema :**
```
┌──────────┐     ┌──────────────┐     ┌─────────────────┐
│ RadioLM  │────▶│ Streaming    │────▶│ Flotte          │
│ (source) │     │ (HLS/Icecast)│     │ vehicules       │
└──────────┘     └──────────────┘     │ (4G/5G + WiFi)  │
                                      └─────────────────┘
```

---

## Deploiement local

### Prerequis materiels

| Composant | Modele recommande | Prix indicatif |
|-----------|-------------------|----------------|
| **SDR** | LimeSDR Mini | ~300€ |
| **SDR (budget)** | PlutoSDR | ~150€ |
| **Antenne** | Dipole Bande III | ~50€ |
| **Filtre** | Passe-bande VHF | ~30€ |

### Installation complete

```bash
# 1. Installer RadioLM
git clone https://github.com/orelmi/FM-streamer.git
cd FM-streamer
pip install -e .

# 2. Installer les outils ODR
sudo ./scripts/install_odr.sh --with-limesdr

# 3. Verifier l'installation
dab-streamer odr check

# 4. Configurer RadioLM
dab-streamer init
```

### Configuration pour diffusion locale

Editer `config.yaml` :

```yaml
dab:
  ensemble_label: "RadioLM Local"
  ensemble_id: "0xF001"      # ID local (eviter conflits)
  ensemble_ecc: "0xE1"       # France
  service_id: "0xF001"
  service_label: "RadioLM"
  bitrate: 64                # kbps
  protection_level: 3        # EEP 3-A

encoder:
  codec: "he-aacv2"
  bitrate: 64
  sample_rate: 48000
```

### Demarrer la diffusion

```bash
# Choisir un canal libre (verifier absence de signal)
dab-streamer odr channels

# Demarrer avec faible puissance (-20 dBm = ~10 uW)
dab-streamer odr start playlist.m3u --channel 12C --power -20

# Ou depuis une entree audio live
dab-streamer odr start alsa:default --channel 12C --power -20
```

### Verification de la reception

1. **Avec un recepteur DAB+** : Scanner les frequences
2. **Avec un SDR** : Utiliser GQRX ou SDR# pour visualiser le signal
3. **Avec un analyseur** : Verifier le spectre OFDM

---

## Integration reseau national

### Etapes pour rejoindre un multiplex

1. **Obtenir une autorisation ARCOM** (ex-CSA)
   - Deposer un dossier de candidature
   - Attendre l'attribution d'une frequence/multiplex

2. **Contacter un diffuseur**
   - TDF : contact@tdf.fr
   - towerCast : contact@towercast.fr

3. **Preparer l'infrastructure studio**
   ```bash
   # Encodeur compatible EDI
   dab-streamer encode file --output-format edi
   ```

4. **Fournir le flux audio**
   - Format : EDI over IP
   - Debit : 64-128 kbps HE-AAC v2
   - Liaison : Fibre/Internet securise

### Specifications techniques pour integration

| Parametre | Exigence |
|-----------|----------|
| **Format audio** | HE-AAC v2 |
| **Debit** | 32-128 kbps |
| **Transport** | EDI over IP (UDP) |
| **Latence** | < 500ms |
| **Disponibilite** | 99.9% |

### Configuration EDI pour operateur

```yaml
# config.yaml - Mode contribution operateur
dab:
  output_format: "edi"
  edi_destination: "192.168.1.100"  # IP multiplexeur operateur
  edi_port: 12000
  edi_source_port: 5004
```

---

## Aspects reglementaires

### Autorisations requises

| Type de diffusion | Autorite | Autorisation |
|-------------------|----------|--------------|
| **Tests < 1mW** | Aucune | Libre |
| **Experimental** | ANFR | Declaration |
| **Local/evenement** | ARCOM + ANFR | Temporaire |
| **National** | ARCOM | Permanente |

### Contacts utiles

| Organisme | Role | Site |
|-----------|------|------|
| **ARCOM** | Regulation audiovisuelle | arcom.fr |
| **ANFR** | Gestion des frequences | anfr.fr |
| **CST** | Conseil superieur technique | cst.fr |

### Puissances autorisees

| Categorie | PAR max | Usage |
|-----------|---------|-------|
| **Experimental** | 1 W | Tests R&D |
| **Local** | 100 W - 1 kW | Ville |
| **Regional** | 1 - 10 kW | Region |
| **National** | 10 - 100 kW | Points hauts |

**PAR** = Puissance Apparente Rayonnee

---

## Exemple de deploiement complet

### Scenario : Radio locale en DAB+

**Objectif :** Diffuser une radio locale sur DAB+ dans une agglomeration.

**Etapes :**

1. **Obtenir l'autorisation ARCOM**
   - Dossier de candidature
   - Zone de couverture souhaitee
   - Contenu editorial

2. **Installer RadioLM au studio**
   ```bash
   pip install dab-streamer
   dab-streamer init
   ```

3. **Configurer l'encodeur**
   ```yaml
   # config.yaml
   dab:
     service_label: "Ma Radio Locale"
     bitrate: 64
   encoder:
     codec: "he-aacv2"
   ```

4. **Connecter au diffuseur**
   ```bash
   # Flux EDI vers TDF/towerCast
   dab-streamer broadcast start --output-format edi \
     --destination operateur.tdf.fr:12000
   ```

5. **Superviser la diffusion**
   ```bash
   # Interface web
   dab-streamer web --port 8080
   ```

---

## Ressources supplementaires

- [Open Digital Radio](https://www.opendigitalradio.org/) - Outils open source
- [WorldDAB](https://www.worlddab.org/) - Organisation mondiale DAB
- [ARCOM](https://www.arcom.fr/) - Regulateur francais
- [TDF](https://www.tdf.fr/) - Diffuseur national
- [towerCast](https://www.towercast.fr/) - Diffuseur NRJ Group

---

## Support

Pour toute question sur le deploiement :
- Issues GitHub : https://github.com/orelmi/FM-streamer/issues
- Documentation ODR : https://www.opendigitalradio.org/mmbtools
