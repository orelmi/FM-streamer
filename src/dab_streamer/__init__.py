"""
DAB+ Podcast Streamer - Logiciel de diffusion podcast DAB+

Ce logiciel permet de:
- Télécharger et gérer des podcasts depuis des flux RSS
- Encoder l'audio au format HE-AAC (requis pour DAB+)
- Générer des flux DAB+ compatibles avec les multiplexeurs
- Programmer la diffusion automatique de podcasts

Copyright (c) 2024 FM-Streamer Team
"""

__version__ = "1.0.0"
__author__ = "FM-Streamer Team"

from .core.config import Config
from .core.podcast_manager import PodcastManager
from .core.audio_encoder import AudioEncoder
from .core.dab_multiplexer import DABMultiplexer
from .core.scheduler import BroadcastScheduler

__all__ = [
    "Config",
    "PodcastManager",
    "AudioEncoder",
    "DABMultiplexer",
    "BroadcastScheduler",
    "__version__",
]
