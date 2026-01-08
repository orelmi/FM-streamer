# RadioLM - DAB+ Podcast Streamer

Logiciel de diffusion podcast DAB+ pour la France, avec support pour flottes de vehicules.

## Fonctionnalites

- **Gestion des podcasts** : Telechargement automatique depuis flux RSS
- **Encodage DAB+** : Conversion audio en HE-AAC (optimise pour DAB+)
- **Multiplexage DAB+** : Generation de flux compatibles ODR-DabMux
- **Programmation** : Planification automatique des diffusions
- **Interface Web** : Tableau de bord de gestion complet
- **Diffusion Flotte** : Streaming vers vehicules via multicast, Icecast ou HLS

## Installation

### Prerequis

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-pip ffmpeg

# Optionnel : ODR-DabMux pour diffusion DAB+ reelle
# https://www.opendigitalradio.org/
```

### Installation du package

```bash
# Cloner le depot
git clone https://github.com/orelmi/FM-streamer.git
cd FM-streamer

# Installer en mode developpement
pip install -e .

# Ou installation standard
pip install .
```

## Configuration

### Initialiser la configuration

```bash
dab-streamer init
```

Cela cree un fichier `config.yaml` avec les parametres par defaut.

### Configuration RadioLM (config.yaml)

```yaml
dab:
  ensemble_label: "RadioLM"
  ensemble_id: "0x1234"
  ensemble_ecc: "0xE1"  # France
  service_id: "0x4001"
  service_label: "RadioLM"
  bitrate: 64  # kbps
  output_format: "edi"

encoder:
  codec: "he-aacv2"
  bitrate: 64
  sample_rate: 48000
  channels: 2

podcast:
  download_dir: "./podcasts"
  max_episodes: 10
  auto_cleanup: true
  cleanup_days: 30

web:
  host: "0.0.0.0"
  port: 8080
```

## Utilisation

### Interface en ligne de commande (CLI)

```bash
# Afficher la configuration
dab-streamer config

# Verifier les outils systeme
dab-streamer check

# Ajouter un podcast
dab-streamer podcast add "https://exemple.com/podcast/feed.xml"

# Lister les podcasts
dab-streamer podcast list

# Telecharger les episodes
dab-streamer podcast download <podcast_id>

# Encoder un fichier pour DAB+
dab-streamer encode file audio.mp3

# Demarrer la diffusion
dab-streamer broadcast start

# Ajouter un programme planifie
dab-streamer schedule add "Matinale" <podcast_id> --time 08:00 --repeat daily
```

### Interface Web

```bash
# Demarrer le serveur web
dab-streamer web

# Ou avec options personnalisees
dab-streamer web --host 0.0.0.0 --port 8080
```

Accedez a l'interface sur http://localhost:8080

## Diffusion vers Flotte de Vehicules

RadioLM supporte plusieurs modes de diffusion vers une flotte de vehicules :

### 1. Multicast UDP (Reseau prive)

Ideal pour :
- Depot/entrepot avec wifi prive
- Zone de circulation couverte par reseau d'entreprise

```python
from dab_streamer.core import NetworkStreamer, FleetConfig, StreamProtocol

streamer = NetworkStreamer(config)
streamer.configure_fleet(FleetConfig(
    protocol=StreamProtocol.MULTICAST_UDP,
    multicast_group="239.255.0.1",
    multicast_port=5004,
    audio_bitrate=64,
))
streamer.start_stream("audio.mp3")
```

### 2. Icecast (Streaming HTTP)

Ideal pour :
- Flotte dispersee geographiquement
- Vehicules avec connexion 4G/5G

```python
streamer.configure_fleet(FleetConfig(
    protocol=StreamProtocol.ICECAST,
    icecast_host="votre-serveur.com",
    icecast_port=8000,
    icecast_mount="/radiolm",
    icecast_password="votre_mot_de_passe",
))
streamer.start_stream("audio.mp3")
```

### 3. HLS (HTTP Live Streaming)

Ideal pour :
- Compatibilite maximale (iOS, Android, autoradios modernes)
- Distribution via CDN
- Connexions instables

```python
streamer.configure_fleet(FleetConfig(
    protocol=StreamProtocol.HLS,
    hls_output_dir="./hls_output",
    hls_segment_duration=6,
))
streamer.start_stream("audio.mp3")
```

## Architecture

```
src/dab_streamer/
├── __init__.py           # Module principal
├── cli.py                # Interface ligne de commande
├── core/
│   ├── config.py         # Gestion de la configuration
│   ├── podcast_manager.py # Gestion des podcasts/RSS
│   ├── audio_encoder.py  # Encodage audio DAB+
│   ├── dab_multiplexer.py # Multiplexage DAB+
│   ├── scheduler.py      # Planification
│   └── network_streamer.py # Streaming reseau/flotte
└── web/
    ├── app.py            # Application Flask
    ├── templates/        # Templates HTML
    └── static/           # CSS/JS
```

## Parametres DAB+ pour la France

| Parametre | Valeur | Description |
|-----------|--------|-------------|
| ECC | 0xE1 | Extended Country Code France |
| Ensemble ID | 0x1234 | Identifiant unique du multiplex |
| Protection | EEP 3-A | Niveau de protection recommande |
| Codec | HE-AAC v2 | Codec optimal pour bas debit |
| Bitrate | 64 kbps | Debit recommande pour podcast |

## Diffusion DAB+ Reelle (ODR)

RadioLM integre les outils Open Digital Radio (ODR) pour une diffusion DAB+ reelle sur les ondes.

**ATTENTION: La diffusion radio est reglementee! En France, une autorisation CSA/ARCEP est requise.**

### Installation des outils ODR

```bash
# Installation automatique (Ubuntu/Debian)
sudo ./scripts/install_odr.sh

# Avec support LimeSDR
sudo ./scripts/install_odr.sh --with-limesdr

# Verifier l'installation
dab-streamer odr check
```

### Demarrer une diffusion DAB+ reelle

```bash
# Lister les canaux disponibles en France
dab-streamer odr channels

# Demarrer la diffusion sur le canal 12C
dab-streamer odr start audio.mp3 --channel 12C

# Avec entree audio ALSA
dab-streamer odr start alsa:default --channel 12C

# Mettre a jour le texte defilant (DLS)
dab-streamer odr dls "RadioLM - Votre podcast du jour"

# Arreter la diffusion
dab-streamer odr stop
```

### Materiel requis

| Materiel | Description |
|----------|-------------|
| LimeSDR | SDR recommande pour DAB+ |
| PlutoSDR | Alternative economique |
| HackRF | Pour tests (puissance limitee) |
| Antenne | Antenne accordee Bande III (174-240 MHz) |

### Canaux DAB+ France (Bande III)

Les canaux les plus courants en France :
- **5A-5D** : 174.928 - 180.064 MHz
- **6A-6D** : 181.936 - 187.072 MHz
- **12A-12D** : 223.936 - 229.072 MHz

Utilisez `dab-streamer odr channels` pour la liste complete.

## Developpement

```bash
# Installer les dependances de developpement
pip install -e ".[dev]"

# Lancer les tests
pytest

# Formatage du code
black src/
```

## Licence

MIT License - Voir [LICENSE](LICENSE)

## Support

Pour signaler un bug ou demander une fonctionnalite :
https://github.com/orelmi/FM-streamer/issues
