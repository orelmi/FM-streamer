"""
Configuration manager for DAB+ Podcast Streamer
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DABConfig:
    """Configuration pour le flux DAB+"""
    ensemble_label: str = "RadioLM"  # Nom de l'ensemble DAB+ (configurable)
    ensemble_id: str = "0x1234"
    ensemble_ecc: str = "0xE1"  # Extended Country Code (France)
    service_id: str = "0x4001"
    service_label: str = "RadioLM"  # Nom du service (configurable)
    component_id: int = 1
    subchannel_id: int = 1
    protection_level: int = 3  # EEP 3-A
    bitrate: int = 64  # kbps
    sample_rate: int = 48000
    channels: int = 2
    output_format: str = "edi"  # edi, eti, ou zmq


@dataclass
class PodcastConfig:
    """Configuration pour les podcasts"""
    download_dir: str = "./podcasts"
    max_episodes: int = 10
    auto_cleanup: bool = True
    cleanup_days: int = 30


@dataclass
class EncoderConfig:
    """Configuration pour l'encodeur audio"""
    codec: str = "he-aacv2"  # he-aacv1, he-aacv2, aac-lc
    bitrate: int = 64
    sample_rate: int = 48000
    channels: int = 2
    ffmpeg_path: str = "ffmpeg"
    odr_audioenc_path: str = "odr-audioenc"


@dataclass
class WebConfig:
    """Configuration pour l'interface web"""
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    secret_key: str = "change-me-in-production"


@dataclass
class Config:
    """Configuration principale"""
    dab: DABConfig = field(default_factory=DABConfig)
    podcast: PodcastConfig = field(default_factory=PodcastConfig)
    encoder: EncoderConfig = field(default_factory=EncoderConfig)
    web: WebConfig = field(default_factory=WebConfig)
    log_level: str = "INFO"
    data_dir: str = "./data"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Charge la configuration depuis un fichier YAML"""
        if config_path is None:
            config_path = os.environ.get("DAB_STREAMER_CONFIG", "config.yaml")

        config = cls()

        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            if "dab" in data:
                config.dab = DABConfig(**data["dab"])
            if "podcast" in data:
                config.podcast = PodcastConfig(**data["podcast"])
            if "encoder" in data:
                config.encoder = EncoderConfig(**data["encoder"])
            if "web" in data:
                config.web = WebConfig(**data["web"])
            if "log_level" in data:
                config.log_level = data["log_level"]
            if "data_dir" in data:
                config.data_dir = data["data_dir"]

        # Créer les répertoires nécessaires
        os.makedirs(config.data_dir, exist_ok=True)
        os.makedirs(config.podcast.download_dir, exist_ok=True)

        return config

    def save(self, config_path: str = "config.yaml") -> None:
        """Sauvegarde la configuration dans un fichier YAML"""
        data = {
            "dab": {
                "ensemble_label": self.dab.ensemble_label,
                "ensemble_id": self.dab.ensemble_id,
                "ensemble_ecc": self.dab.ensemble_ecc,
                "service_id": self.dab.service_id,
                "service_label": self.dab.service_label,
                "component_id": self.dab.component_id,
                "subchannel_id": self.dab.subchannel_id,
                "protection_level": self.dab.protection_level,
                "bitrate": self.dab.bitrate,
                "sample_rate": self.dab.sample_rate,
                "channels": self.dab.channels,
                "output_format": self.dab.output_format,
            },
            "podcast": {
                "download_dir": self.podcast.download_dir,
                "max_episodes": self.podcast.max_episodes,
                "auto_cleanup": self.podcast.auto_cleanup,
                "cleanup_days": self.podcast.cleanup_days,
            },
            "encoder": {
                "codec": self.encoder.codec,
                "bitrate": self.encoder.bitrate,
                "sample_rate": self.encoder.sample_rate,
                "channels": self.encoder.channels,
                "ffmpeg_path": self.encoder.ffmpeg_path,
                "odr_audioenc_path": self.encoder.odr_audioenc_path,
            },
            "web": {
                "host": self.web.host,
                "port": self.web.port,
                "debug": self.web.debug,
                "secret_key": self.web.secret_key,
            },
            "log_level": self.log_level,
            "data_dir": self.data_dir,
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    @staticmethod
    def create_default_config(config_path: str = "config.yaml") -> "Config":
        """Crée un fichier de configuration par défaut"""
        config = Config()
        config.save(config_path)
        return config
