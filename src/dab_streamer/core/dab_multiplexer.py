"""
DAB+ Multiplexer - Génération de flux DAB+ et configuration du multiplexeur
"""

import os
import json
import socket
import struct
import logging
import subprocess
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
from datetime import datetime

from .config import Config, DABConfig

logger = logging.getLogger(__name__)


class ProtectionLevel(Enum):
    """Niveaux de protection EEP pour DAB+"""
    EEP_1A = 1  # Plus haute protection, plus de bits
    EEP_2A = 2
    EEP_3A = 3  # Recommandé pour DAB+
    EEP_4A = 4  # Moins de protection, moins de bits


class OutputFormat(Enum):
    """Formats de sortie du multiplexeur"""
    EDI = "edi"       # Encapsulated Data Interface (UDP/TCP)
    ETI = "eti"       # Ensemble Transport Interface (fichier/fifo)
    ZMQ = "zmq"       # ZeroMQ (pour ODR-DabMod)


@dataclass
class DABService:
    """Service DAB+ (une station/programme)"""
    id: str
    label: str
    short_label: str = ""
    language: int = 0x08  # Français
    programme_type: int = 0  # Aucun type spécifique

    def __post_init__(self):
        if not self.short_label:
            self.short_label = self.label[:8]


@dataclass
class DABSubchannel:
    """Sous-canal DAB+ (flux audio)"""
    id: int
    bitrate: int  # en kbps
    protection: ProtectionLevel = ProtectionLevel.EEP_3A
    input_file: str = ""
    input_type: str = "file"  # file, fifo, zmq, alsa


@dataclass
class DABComponent:
    """Composant DAB+ (lie service et sous-canal)"""
    id: int
    service_id: str
    subchannel_id: int
    type: int = 0  # 0 = Audio
    label: str = ""


@dataclass
class DABEnsemble:
    """Ensemble DAB+ (multiplex complet)"""
    id: str
    ecc: str
    label: str
    short_label: str = ""
    local_time_offset: int = 1  # UTC+1 pour la France

    def __post_init__(self):
        if not self.short_label:
            self.short_label = self.label[:8]


@dataclass
class PADData:
    """Programme Associated Data (métadonnées DAB+)"""
    dls_text: str = ""  # Dynamic Label Segment (texte défilant)
    slide_file: str = ""  # Image MOT Slideshow
    updated: datetime = field(default_factory=datetime.now)


class DABMultiplexer:
    """Gestionnaire du multiplexeur DAB+"""

    def __init__(self, config: Config):
        self.config = config
        self.dab_config = config.dab

        # Configuration de l'ensemble
        self.ensemble = DABEnsemble(
            id=config.dab.ensemble_id,
            ecc=config.dab.ensemble_ecc,
            label=config.dab.ensemble_label,
        )

        # Services, sous-canaux et composants
        self.services: dict[str, DABService] = {}
        self.subchannels: dict[int, DABSubchannel] = {}
        self.components: dict[int, DABComponent] = {}

        # PAD pour chaque service
        self.pad_data: dict[str, PADData] = {}

        # Processus du multiplexeur
        self.mux_process: Optional[subprocess.Popen] = None
        self.is_running = False

        # Répertoires
        self.config_dir = Path(config.data_dir) / "dab_config"
        self.fifo_dir = Path(config.data_dir) / "fifos"
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.fifo_dir, exist_ok=True)

        # Vérifier ODR-DabMux
        self.odr_dabmux_available = self._check_odr_dabmux()

    def _check_odr_dabmux(self) -> bool:
        """Vérifie si ODR-DabMux est disponible"""
        try:
            result = subprocess.run(
                ["odr-dabmux", "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def add_service(self, service: DABService) -> None:
        """Ajoute un service au multiplex"""
        self.services[service.id] = service
        self.pad_data[service.id] = PADData()
        logger.info(f"Service ajouté: {service.label} (ID: {service.id})")

    def add_subchannel(self, subchannel: DABSubchannel) -> None:
        """Ajoute un sous-canal au multiplex"""
        self.subchannels[subchannel.id] = subchannel
        logger.info(f"Sous-canal ajouté: ID={subchannel.id}, bitrate={subchannel.bitrate}k")

    def add_component(self, component: DABComponent) -> None:
        """Ajoute un composant au multiplex"""
        self.components[component.id] = component
        logger.info(f"Composant ajouté: ID={component.id}")

    def create_default_service(self, label: str = "Podcasts") -> str:
        """Crée un service par défaut pour les podcasts"""
        service_id = self.dab_config.service_id

        service = DABService(
            id=service_id,
            label=label,
            short_label=label[:8],
        )
        self.add_service(service)

        subchannel = DABSubchannel(
            id=self.dab_config.subchannel_id,
            bitrate=self.dab_config.bitrate,
            protection=ProtectionLevel(self.dab_config.protection_level),
        )
        self.add_subchannel(subchannel)

        component = DABComponent(
            id=self.dab_config.component_id,
            service_id=service_id,
            subchannel_id=subchannel.id,
        )
        self.add_component(component)

        return service_id

    def generate_mux_config(self, output_path: Optional[str] = None) -> str:
        """
        Génère la configuration pour ODR-DabMux

        Returns:
            Chemin du fichier de configuration généré
        """
        if output_path is None:
            output_path = str(self.config_dir / "dabmux.mux")

        config_lines = []

        # Section générale
        config_lines.append("; Configuration générée par DAB+ Podcast Streamer")
        config_lines.append(f"; Date: {datetime.now().isoformat()}")
        config_lines.append("")

        # Section general
        config_lines.append("general {")
        config_lines.append(f'    dabmode 1')
        config_lines.append(f'    nbframes 0')
        config_lines.append("}")
        config_lines.append("")

        # Section remotecontrol
        config_lines.append("remotecontrol {")
        config_lines.append('    telnetport 12721')
        config_lines.append("}")
        config_lines.append("")

        # Section ensemble
        config_lines.append("ensemble {")
        config_lines.append(f'    id {self.ensemble.id}')
        config_lines.append(f'    ecc {self.ensemble.ecc}')
        config_lines.append(f'    local-time-offset {self.ensemble.local_time_offset}')
        config_lines.append(f'    label "{self.ensemble.label}"')
        config_lines.append(f'    shortlabel "{self.ensemble.short_label}"')
        config_lines.append("}")
        config_lines.append("")

        # Section services
        config_lines.append("services {")
        for service in self.services.values():
            config_lines.append(f'    srv-{service.id} {{')
            config_lines.append(f'        id {service.id}')
            config_lines.append(f'        label "{service.label}"')
            config_lines.append(f'        shortlabel "{service.short_label}"')
            config_lines.append(f'        language {service.language}')
            config_lines.append(f'        pty {service.programme_type}')
            config_lines.append('    }')
        config_lines.append("}")
        config_lines.append("")

        # Section subchannels
        config_lines.append("subchannels {")
        for subchannel in self.subchannels.values():
            config_lines.append(f'    sub-{subchannel.id} {{')
            config_lines.append(f'        type dabplus')
            config_lines.append(f'        bitrate {subchannel.bitrate}')
            config_lines.append(f'        id {subchannel.id}')
            config_lines.append(f'        protection {subchannel.protection.value}')

            if subchannel.input_type == "file":
                config_lines.append(f'        inputfile "{subchannel.input_file}"')
            elif subchannel.input_type == "fifo":
                config_lines.append(f'        inputfile "{subchannel.input_file}"')
            elif subchannel.input_type == "zmq":
                config_lines.append(f'        inputuri "{subchannel.input_file}"')

            config_lines.append('    }')
        config_lines.append("}")
        config_lines.append("")

        # Section components
        config_lines.append("components {")
        for component in self.components.values():
            config_lines.append(f'    comp-{component.id} {{')
            config_lines.append(f'        service srv-{component.service_id}')
            config_lines.append(f'        subchannel sub-{component.subchannel_id}')
            config_lines.append(f'        type {component.type}')
            if component.label:
                config_lines.append(f'        label "{component.label}"')
            config_lines.append('    }')
        config_lines.append("}")
        config_lines.append("")

        # Section outputs
        config_lines.append("outputs {")
        output_format = self.dab_config.output_format

        if output_format == "edi":
            config_lines.append('    edi {')
            config_lines.append('        destinations {')
            config_lines.append('            edi_udp {')
            config_lines.append('                protocol udp')
            config_lines.append('                destination "127.0.0.1"')
            config_lines.append('                port 12000')
            config_lines.append('            }')
            config_lines.append('        }')
            config_lines.append('    }')
        elif output_format == "eti":
            eti_path = str(self.config_dir / "output.eti")
            config_lines.append(f'    eti "{eti_path}"')
        elif output_format == "zmq":
            config_lines.append('    zmq "tcp://*:18081"')

        config_lines.append("}")

        # Écrire le fichier
        config_content = "\n".join(config_lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        logger.info(f"Configuration générée: {output_path}")
        return output_path

    def create_fifo(self, name: str) -> str:
        """Crée un FIFO pour l'entrée audio"""
        fifo_path = self.fifo_dir / name
        if not fifo_path.exists():
            os.mkfifo(fifo_path)
        return str(fifo_path)

    def start_multiplexer(self, config_path: Optional[str] = None) -> bool:
        """Démarre le multiplexeur DAB+"""
        if not self.odr_dabmux_available:
            logger.error("ODR-DabMux n'est pas disponible")
            return False

        if self.is_running:
            logger.warning("Le multiplexeur est déjà en cours d'exécution")
            return False

        if config_path is None:
            config_path = self.generate_mux_config()

        cmd = ["odr-dabmux", config_path]

        try:
            self.mux_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.is_running = True
            logger.info("Multiplexeur DAB+ démarré")

            # Démarrer un thread pour surveiller le processus
            monitor_thread = threading.Thread(target=self._monitor_process)
            monitor_thread.daemon = True
            monitor_thread.start()

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur au démarrage du multiplexeur: {e}")
            return False

    def _monitor_process(self) -> None:
        """Surveille le processus du multiplexeur"""
        if self.mux_process:
            self.mux_process.wait()
            self.is_running = False
            logger.info("Multiplexeur DAB+ arrêté")

    def stop_multiplexer(self) -> None:
        """Arrête le multiplexeur DAB+"""
        if self.mux_process and self.is_running:
            self.mux_process.terminate()
            self.mux_process.wait(timeout=10)
            self.is_running = False
            logger.info("Multiplexeur DAB+ arrêté")

    def update_pad(
        self,
        service_id: str,
        dls_text: Optional[str] = None,
        slide_file: Optional[str] = None,
    ) -> None:
        """
        Met à jour les métadonnées PAD (Programme Associated Data)

        Args:
            service_id: ID du service
            dls_text: Texte du Dynamic Label Segment
            slide_file: Chemin de l'image pour MOT Slideshow
        """
        if service_id not in self.pad_data:
            self.pad_data[service_id] = PADData()

        pad = self.pad_data[service_id]

        if dls_text is not None:
            pad.dls_text = dls_text[:128]  # Max 128 caractères
        if slide_file is not None:
            pad.slide_file = slide_file

        pad.updated = datetime.now()

        logger.debug(f"PAD mis à jour pour {service_id}: {dls_text}")

    def get_status(self) -> dict:
        """Retourne l'état actuel du multiplexeur"""
        return {
            "running": self.is_running,
            "odr_dabmux_available": self.odr_dabmux_available,
            "ensemble": {
                "id": self.ensemble.id,
                "label": self.ensemble.label,
            },
            "services": len(self.services),
            "subchannels": len(self.subchannels),
            "components": len(self.components),
        }


class EDIOutput:
    """Générateur de flux EDI (Encapsulated Data Interface)"""

    def __init__(self, destination: str = "127.0.0.1", port: int = 12000):
        self.destination = destination
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.sequence_number = 0

    def connect(self) -> bool:
        """Établit la connexion UDP"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            return True
        except socket.error as e:
            logger.error(f"Erreur de connexion EDI: {e}")
            return False

    def send_frame(self, frame_data: bytes) -> bool:
        """Envoie une trame EDI"""
        if not self.socket:
            return False

        try:
            # En-tête EDI simplifié
            header = struct.pack(
                ">BBHI",
                0xAF,  # Sync byte
                0x01,  # Protocol version
                len(frame_data),
                self.sequence_number,
            )

            packet = header + frame_data
            self.socket.sendto(packet, (self.destination, self.port))
            self.sequence_number = (self.sequence_number + 1) % 0xFFFFFFFF
            return True

        except socket.error as e:
            logger.error(f"Erreur d'envoi EDI: {e}")
            return False

    def close(self) -> None:
        """Ferme la connexion"""
        if self.socket:
            self.socket.close()
            self.socket = None


class DABStreamPlayer:
    """Lecteur de flux DAB+ pour diffusion de podcasts"""

    def __init__(self, multiplexer: DABMultiplexer, encoder):
        self.multiplexer = multiplexer
        self.encoder = encoder
        self.current_file: Optional[str] = None
        self.is_playing = False
        self.encoder_process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._play_thread: Optional[threading.Thread] = None
        self.on_track_finished: Optional[Callable[[str], None]] = None

    def play(self, audio_file: str, service_id: str) -> bool:
        """
        Lance la lecture d'un fichier audio vers le flux DAB+

        Args:
            audio_file: Chemin du fichier audio
            service_id: ID du service DAB+

        Returns:
            True si la lecture a démarré
        """
        if self.is_playing:
            self.stop()

        if not os.path.exists(audio_file):
            logger.error(f"Fichier non trouvé: {audio_file}")
            return False

        # Obtenir le sous-canal associé au service
        component = next(
            (c for c in self.multiplexer.components.values()
             if c.service_id == service_id),
            None
        )

        if not component:
            logger.error(f"Service non trouvé: {service_id}")
            return False

        subchannel = self.multiplexer.subchannels.get(component.subchannel_id)
        if not subchannel:
            logger.error(f"Sous-canal non trouvé: {component.subchannel_id}")
            return False

        self.current_file = audio_file
        self.is_playing = True
        self._stop_event.clear()

        # Démarrer l'encodage vers le FIFO
        fifo_path = subchannel.input_file

        self._play_thread = threading.Thread(
            target=self._play_loop,
            args=(audio_file, fifo_path, service_id),
        )
        self._play_thread.daemon = True
        self._play_thread.start()

        logger.info(f"Lecture démarrée: {audio_file}")
        return True

    def _play_loop(self, audio_file: str, fifo_path: str, service_id: str) -> None:
        """Boucle de lecture"""
        try:
            self.encoder_process = self.encoder.encode_for_dab_stream(
                audio_file,
                fifo_path,
            )

            # Attendre la fin de l'encodage ou l'arrêt
            while self.encoder_process.poll() is None:
                if self._stop_event.is_set():
                    self.encoder_process.terminate()
                    break
                time.sleep(0.1)

            self.is_playing = False

            # Notifier la fin de la lecture
            if self.on_track_finished and not self._stop_event.is_set():
                self.on_track_finished(audio_file)

        except Exception as e:
            logger.error(f"Erreur de lecture: {e}")
            self.is_playing = False

    def stop(self) -> None:
        """Arrête la lecture en cours"""
        self._stop_event.set()

        if self.encoder_process:
            self.encoder_process.terminate()
            self.encoder_process = None

        if self._play_thread:
            self._play_thread.join(timeout=5)
            self._play_thread = None

        self.is_playing = False
        self.current_file = None
        logger.info("Lecture arrêtée")

    def get_status(self) -> dict:
        """Retourne l'état actuel du lecteur"""
        return {
            "playing": self.is_playing,
            "current_file": self.current_file,
        }
