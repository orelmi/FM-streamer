"""
Network Streamer - Diffusion vers flotte de véhicules via réseau IP

Ce module permet de diffuser des podcasts vers une flotte de véhicules
via différents protocoles réseau:
- Multicast UDP (pour réseau local)
- Unicast UDP/TCP (vers serveurs de distribution)
- HTTP Streaming (HLS/DASH pour réception mobile)
- RTSP (pour systèmes embarqués)
"""

import os
import socket
import struct
import logging
import threading
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
from datetime import datetime

from .config import Config

logger = logging.getLogger(__name__)


class StreamProtocol(Enum):
    """Protocoles de streaming supportés"""
    MULTICAST_UDP = "multicast_udp"  # Multicast pour réseau local/entreprise
    UNICAST_UDP = "unicast_udp"      # Unicast UDP vers serveur
    ICECAST = "icecast"              # Icecast pour streaming HTTP
    HLS = "hls"                      # HTTP Live Streaming (Apple)
    DASH = "dash"                    # MPEG-DASH


@dataclass
class FleetConfig:
    """Configuration pour diffusion vers flotte de véhicules"""
    # Protocole de diffusion
    protocol: StreamProtocol = StreamProtocol.MULTICAST_UDP

    # Multicast UDP (pour réseau privé d'entreprise)
    multicast_group: str = "239.255.0.1"  # Groupe multicast privé
    multicast_port: int = 5004
    multicast_ttl: int = 32  # Time-to-live (portée réseau)

    # Unicast vers serveur de distribution
    destination_host: str = "localhost"
    destination_port: int = 8000

    # Icecast (pour streaming HTTP vers flotte)
    icecast_host: str = "localhost"
    icecast_port: int = 8000
    icecast_mount: str = "/radiolm"
    icecast_password: str = "hackme"

    # HLS/DASH
    hls_output_dir: str = "./hls_output"
    hls_segment_duration: int = 6  # secondes
    hls_playlist_size: int = 5     # nombre de segments dans la playlist

    # Paramètres audio pour véhicules
    audio_bitrate: int = 64        # kbps (adapté réseau mobile)
    sample_rate: int = 48000
    channels: int = 2              # Stéréo

    # France spécifique
    region: str = "FR"             # Code pays
    timezone: str = "Europe/Paris"


@dataclass
class VehicleInfo:
    """Information sur un véhicule de la flotte"""
    id: str
    name: str
    ip_address: str
    last_seen: datetime = field(default_factory=datetime.now)
    is_connected: bool = False
    current_position: Optional[tuple[float, float]] = None  # lat, lon


class NetworkStreamer:
    """
    Streamer réseau pour diffusion vers flotte de véhicules

    Supporte plusieurs modes de diffusion:
    - Multicast UDP: idéal pour réseau privé d'entreprise
    - Icecast: streaming HTTP standard
    - HLS: compatible avec tous les appareils mobiles
    """

    def __init__(self, config: Config):
        self.config = config
        self.fleet_config = FleetConfig()

        # État
        self.is_streaming = False
        self.stream_process: Optional[subprocess.Popen] = None
        self.vehicles: dict[str, VehicleInfo] = {}

        # Socket multicast
        self.multicast_socket: Optional[socket.socket] = None

        # Thread de streaming
        self._stop_event = threading.Event()
        self._stream_thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_vehicle_connected: Optional[Callable[[VehicleInfo], None]] = None
        self.on_vehicle_disconnected: Optional[Callable[[VehicleInfo], None]] = None

        # Répertoires
        self.output_dir = Path(config.data_dir) / "stream_output"
        os.makedirs(self.output_dir, exist_ok=True)

    def configure_fleet(self, fleet_config: FleetConfig) -> None:
        """Configure les paramètres de diffusion pour la flotte"""
        self.fleet_config = fleet_config
        logger.info(f"Configuration flotte: {fleet_config.protocol.value}")

    def start_multicast_stream(self, audio_source: str) -> bool:
        """
        Démarre un stream multicast UDP vers la flotte

        Idéal pour:
        - Réseau privé d'entreprise (dépôt, entrepôt)
        - Wifi d'entreprise couvrant la zone de circulation
        - VPN d'entreprise vers véhicules

        Args:
            audio_source: Chemin du fichier ou FIFO source

        Returns:
            True si le stream a démarré
        """
        if self.is_streaming:
            self.stop_stream()

        fc = self.fleet_config

        # Construire la commande FFmpeg pour multicast
        cmd = [
            self.config.encoder.ffmpeg_path,
            "-re",  # Lecture temps réel
            "-i", audio_source,
            "-ar", str(fc.sample_rate),
            "-ac", str(fc.channels),
            "-c:a", "aac",
            "-b:a", f"{fc.audio_bitrate}k",
            "-f", "rtp",
            f"rtp://{fc.multicast_group}:{fc.multicast_port}?ttl={fc.multicast_ttl}"
        ]

        try:
            self.stream_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.is_streaming = True

            # Générer le fichier SDP pour les clients
            sdp_content = self._generate_sdp(fc)
            sdp_path = self.output_dir / "radiolm.sdp"
            with open(sdp_path, "w") as f:
                f.write(sdp_content)

            logger.info(f"Stream multicast démarré: {fc.multicast_group}:{fc.multicast_port}")
            logger.info(f"Fichier SDP généré: {sdp_path}")

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur démarrage multicast: {e}")
            return False

    def _generate_sdp(self, fc: FleetConfig) -> str:
        """Génère un fichier SDP pour les clients multicast"""
        return f"""v=0
o=- 0 0 IN IP4 {fc.multicast_group}
s=RadioLM - Diffusion Flotte
c=IN IP4 {fc.multicast_group}/{fc.multicast_ttl}
t=0 0
a=recvonly
m=audio {fc.multicast_port} RTP/AVP 96
a=rtpmap:96 mpeg4-generic/{fc.sample_rate}/{fc.channels}
a=fmtp:96 profile-level-id=1;mode=AAC-hbr;sizelength=13;indexlength=3;indexdeltalength=3
"""

    def start_icecast_stream(self, audio_source: str) -> bool:
        """
        Démarre un stream Icecast vers la flotte

        Idéal pour:
        - Distribution via internet (4G/5G)
        - Flotte dispersée géographiquement
        - Véhicules avec connexion mobile

        Args:
            audio_source: Chemin du fichier ou FIFO source

        Returns:
            True si le stream a démarré
        """
        if self.is_streaming:
            self.stop_stream()

        fc = self.fleet_config

        # URL Icecast
        icecast_url = (
            f"icecast://source:{fc.icecast_password}@"
            f"{fc.icecast_host}:{fc.icecast_port}{fc.icecast_mount}"
        )

        # Commande FFmpeg pour Icecast
        cmd = [
            self.config.encoder.ffmpeg_path,
            "-re",
            "-i", audio_source,
            "-ar", str(fc.sample_rate),
            "-ac", str(fc.channels),
            "-c:a", "libmp3lame",  # MP3 pour compatibilité maximale
            "-b:a", f"{fc.audio_bitrate}k",
            "-content_type", "audio/mpeg",
            "-f", "mp3",
            icecast_url
        ]

        try:
            self.stream_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.is_streaming = True

            logger.info(f"Stream Icecast démarré: http://{fc.icecast_host}:{fc.icecast_port}{fc.icecast_mount}")

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur démarrage Icecast: {e}")
            return False

    def start_hls_stream(self, audio_source: str) -> bool:
        """
        Démarre un stream HLS (HTTP Live Streaming)

        Idéal pour:
        - Compatibilité maximale (iOS, Android, autoradios modernes)
        - Distribution via CDN
        - Connexions instables (mise en buffer)

        Args:
            audio_source: Chemin du fichier ou FIFO source

        Returns:
            True si le stream a démarré
        """
        if self.is_streaming:
            self.stop_stream()

        fc = self.fleet_config
        hls_dir = Path(fc.hls_output_dir)
        os.makedirs(hls_dir, exist_ok=True)

        playlist_path = hls_dir / "radiolm.m3u8"
        segment_path = hls_dir / "radiolm_%03d.ts"

        # Commande FFmpeg pour HLS
        cmd = [
            self.config.encoder.ffmpeg_path,
            "-re",
            "-i", audio_source,
            "-ar", str(fc.sample_rate),
            "-ac", str(fc.channels),
            "-c:a", "aac",
            "-b:a", f"{fc.audio_bitrate}k",
            "-f", "hls",
            "-hls_time", str(fc.hls_segment_duration),
            "-hls_list_size", str(fc.hls_playlist_size),
            "-hls_flags", "delete_segments",
            str(playlist_path)
        ]

        try:
            self.stream_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.is_streaming = True

            logger.info(f"Stream HLS démarré: {playlist_path}")
            logger.info(f"Servez le répertoire {hls_dir} via HTTP pour que les véhicules puissent accéder au flux")

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur démarrage HLS: {e}")
            return False

    def start_stream(self, audio_source: str) -> bool:
        """
        Démarre le stream selon le protocole configuré

        Args:
            audio_source: Chemin du fichier ou FIFO source

        Returns:
            True si le stream a démarré
        """
        protocol = self.fleet_config.protocol

        if protocol == StreamProtocol.MULTICAST_UDP:
            return self.start_multicast_stream(audio_source)
        elif protocol == StreamProtocol.ICECAST:
            return self.start_icecast_stream(audio_source)
        elif protocol == StreamProtocol.HLS:
            return self.start_hls_stream(audio_source)
        else:
            logger.error(f"Protocole non supporté: {protocol}")
            return False

    def stop_stream(self) -> None:
        """Arrête le stream en cours"""
        self._stop_event.set()

        if self.stream_process:
            self.stream_process.terminate()
            self.stream_process.wait(timeout=10)
            self.stream_process = None

        if self.multicast_socket:
            self.multicast_socket.close()
            self.multicast_socket = None

        self.is_streaming = False
        logger.info("Stream arrêté")

    def register_vehicle(self, vehicle: VehicleInfo) -> None:
        """Enregistre un véhicule dans la flotte"""
        self.vehicles[vehicle.id] = vehicle
        logger.info(f"Véhicule enregistré: {vehicle.name} ({vehicle.id})")

    def unregister_vehicle(self, vehicle_id: str) -> None:
        """Supprime un véhicule de la flotte"""
        if vehicle_id in self.vehicles:
            del self.vehicles[vehicle_id]
            logger.info(f"Véhicule supprimé: {vehicle_id}")

    def update_vehicle_status(
        self,
        vehicle_id: str,
        is_connected: bool,
        position: Optional[tuple[float, float]] = None
    ) -> None:
        """Met à jour le statut d'un véhicule"""
        if vehicle_id in self.vehicles:
            vehicle = self.vehicles[vehicle_id]
            was_connected = vehicle.is_connected

            vehicle.is_connected = is_connected
            vehicle.last_seen = datetime.now()
            if position:
                vehicle.current_position = position

            # Callbacks
            if is_connected and not was_connected:
                if self.on_vehicle_connected:
                    self.on_vehicle_connected(vehicle)
            elif not is_connected and was_connected:
                if self.on_vehicle_disconnected:
                    self.on_vehicle_disconnected(vehicle)

    def get_fleet_status(self) -> dict:
        """Retourne le statut de la flotte"""
        connected = sum(1 for v in self.vehicles.values() if v.is_connected)

        return {
            "streaming": self.is_streaming,
            "protocol": self.fleet_config.protocol.value,
            "total_vehicles": len(self.vehicles),
            "connected_vehicles": connected,
            "vehicles": [
                {
                    "id": v.id,
                    "name": v.name,
                    "connected": v.is_connected,
                    "last_seen": v.last_seen.isoformat(),
                    "position": v.current_position,
                }
                for v in self.vehicles.values()
            ],
        }

    def get_stream_url(self) -> str:
        """Retourne l'URL de streaming pour les clients"""
        fc = self.fleet_config

        if fc.protocol == StreamProtocol.MULTICAST_UDP:
            return f"rtp://{fc.multicast_group}:{fc.multicast_port}"
        elif fc.protocol == StreamProtocol.ICECAST:
            return f"http://{fc.icecast_host}:{fc.icecast_port}{fc.icecast_mount}"
        elif fc.protocol == StreamProtocol.HLS:
            return f"http://[server]/{fc.hls_output_dir}/radiolm.m3u8"
        else:
            return ""


class FleetMonitor:
    """
    Moniteur de flotte - Suivi des véhicules connectés

    Peut être utilisé pour:
    - Tracker les véhicules qui écoutent
    - Statistiques d'audience
    - Alertes de déconnexion
    """

    def __init__(self, streamer: NetworkStreamer):
        self.streamer = streamer
        self.is_monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Statistiques
        self.stats = {
            "total_play_time": 0,
            "peak_listeners": 0,
            "total_connections": 0,
        }

    def start_monitoring(self, check_interval: int = 30) -> None:
        """Démarre le monitoring de la flotte"""
        if self.is_monitoring:
            return

        self.is_monitoring = True
        self._stop_event.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(check_interval,)
        )
        self._monitor_thread.daemon = True
        self._monitor_thread.start()

        logger.info("Monitoring de la flotte démarré")

    def _monitor_loop(self, interval: int) -> None:
        """Boucle de monitoring"""
        while not self._stop_event.is_set():
            status = self.streamer.get_fleet_status()

            # Mettre à jour les statistiques
            connected = status["connected_vehicles"]
            if connected > self.stats["peak_listeners"]:
                self.stats["peak_listeners"] = connected

            # Vérifier les véhicules inactifs
            now = datetime.now()
            for vehicle in self.streamer.vehicles.values():
                if vehicle.is_connected:
                    inactive_time = (now - vehicle.last_seen).total_seconds()
                    if inactive_time > 300:  # 5 minutes sans signal
                        self.streamer.update_vehicle_status(vehicle.id, False)

            time.sleep(interval)

    def stop_monitoring(self) -> None:
        """Arrête le monitoring"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self.is_monitoring = False
        logger.info("Monitoring de la flotte arrêté")

    def get_statistics(self) -> dict:
        """Retourne les statistiques de la flotte"""
        status = self.streamer.get_fleet_status()
        return {
            **self.stats,
            "current_listeners": status["connected_vehicles"],
            "is_streaming": status["streaming"],
        }
