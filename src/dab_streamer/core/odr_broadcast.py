"""
ODR Broadcast - Diffusion DAB+ reelle avec Open Digital Radio

Ce module integre les outils ODR (Open Digital Radio) pour une diffusion
DAB+ reelle sur les ondes:
- ODR-DabMux: Multiplexeur DAB+
- ODR-DabMod: Modulateur OFDM pour transmission
- ODR-AudioEnc: Encodeur audio DAB+ (alternative a FFmpeg)
- ODR-PadEnc: Encodeur PAD (Dynamic Label, Slideshow)

Documentation: https://www.opendigitalradio.org/
"""

import os
import signal
import subprocess
import threading
import time
import logging
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
from datetime import datetime

from .config import Config

logger = logging.getLogger(__name__)


class TransmissionMode(Enum):
    """Modes de transmission DAB"""
    MODE_I = 1    # 1.536 MHz - terrestre longue portee (France)
    MODE_II = 2   # 1.536 MHz - terrestre/cable
    MODE_III = 3  # 1.536 MHz - satellite/cable
    MODE_IV = 4   # 1.536 MHz - terrestre courte portee


class OutputType(Enum):
    """Types de sortie du modulateur"""
    FILE = "file"           # Fichier IQ
    UHDHACKRF = "uhd"       # USRP/HackRF via UHD
    SOAPYSDR = "soapysdr"   # SoapySDR (LimeSDR, PlutoSDR, etc.)
    ZMQ = "zmq"             # ZeroMQ (vers autre instance)
    LIMESDR = "limesdr"     # LimeSDR direct


@dataclass
class ODRConfig:
    """Configuration pour diffusion ODR DAB+ reelle"""
    # Frequence de transmission (MHz) - Bande III pour la France
    frequency_mhz: float = 225.648  # Canal 12C (France)

    # Puissance de sortie (dBm) - ATTENTION: reglementation!
    output_power_dbm: float = -10.0  # Faible puissance pour tests

    # Mode de transmission
    transmission_mode: TransmissionMode = TransmissionMode.MODE_I

    # Type de sortie
    output_type: OutputType = OutputType.SOAPYSDR

    # Device SDR
    sdr_device: str = "driver=lime"  # LimeSDR par defaut
    sdr_channel: int = 0
    sdr_antenna: str = "BAND2"  # Antenne TX

    # Gain
    digital_gain: float = 0.8
    sdr_gain: float = 60.0

    # Fichiers de configuration ODR
    mux_config_path: str = "./odr_config/dabmux.mux"
    mod_config_path: str = "./odr_config/dabmod.ini"

    # Chemins des executables ODR
    odr_dabmux_path: str = "odr-dabmux"
    odr_dabmod_path: str = "odr-dabmod"
    odr_audioenc_path: str = "odr-audioenc"
    odr_padenc_path: str = "odr-padenc"

    # Ports ZMQ internes
    zmq_mux_output: str = "tcp://127.0.0.1:9100"
    zmq_audio_input: str = "tcp://127.0.0.1:9001"

    # PAD (Programme Associated Data)
    enable_pad: bool = True
    pad_fifo: str = "./odr_config/pad.fifo"
    slide_directory: str = "./slides"


@dataclass
class TransmissionStatus:
    """Status de la transmission"""
    is_running: bool = False
    mux_running: bool = False
    mod_running: bool = False
    encoder_running: bool = False
    frequency_mhz: float = 0.0
    output_power_dbm: float = 0.0
    uptime_seconds: int = 0
    last_error: str = ""
    started_at: Optional[datetime] = None


class ODRBroadcast:
    """
    Gestionnaire de diffusion DAB+ reelle avec ODR

    ATTENTION: La diffusion radio est reglementee!
    - En France: autorisation CSA/ARCEP requise
    - Utilisez une faible puissance pour les tests
    - Ne pas interferer avec les services existants
    """

    # Canaux DAB+ France (Bande III)
    FRANCE_CHANNELS = {
        "5A": 174.928, "5B": 176.640, "5C": 178.352, "5D": 180.064,
        "6A": 181.936, "6B": 183.648, "6C": 185.360, "6D": 187.072,
        "7A": 188.928, "7B": 190.640, "7C": 192.352, "7D": 194.064,
        "8A": 195.936, "8B": 197.648, "8C": 199.360, "8D": 201.072,
        "9A": 202.928, "9B": 204.640, "9C": 206.352, "9D": 208.064,
        "10A": 209.936, "10B": 211.648, "10C": 213.360, "10D": 215.072,
        "11A": 216.928, "11B": 218.640, "11C": 220.352, "11D": 222.064,
        "12A": 223.936, "12B": 225.648, "12C": 227.360, "12D": 229.072,
        "13A": 230.784, "13B": 232.496, "13C": 234.208, "13D": 235.776,
        "13E": 237.488, "13F": 239.200,
    }

    def __init__(self, config: Config):
        self.config = config
        self.odr_config = ODRConfig()

        # Processus
        self.mux_process: Optional[subprocess.Popen] = None
        self.mod_process: Optional[subprocess.Popen] = None
        self.encoder_process: Optional[subprocess.Popen] = None
        self.pad_process: Optional[subprocess.Popen] = None

        # Status
        self.status = TransmissionStatus()

        # Thread de surveillance
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Callbacks
        self.on_status_change: Optional[Callable[[TransmissionStatus], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # Repertoires
        self.config_dir = Path(config.data_dir) / "odr_config"
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.config_dir / "slides", exist_ok=True)

        # Verifier les outils ODR
        self.odr_tools_available = self._check_odr_tools()

    def _check_odr_tools(self) -> dict[str, bool]:
        """Verifie la disponibilite des outils ODR"""
        tools = {}

        for tool_name, tool_path in [
            ("odr-dabmux", self.odr_config.odr_dabmux_path),
            ("odr-dabmod", self.odr_config.odr_dabmod_path),
            ("odr-audioenc", self.odr_config.odr_audioenc_path),
            ("odr-padenc", self.odr_config.odr_padenc_path),
        ]:
            try:
                result = subprocess.run(
                    [tool_path, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                tools[tool_name] = True
            except (subprocess.SubprocessError, FileNotFoundError):
                tools[tool_name] = False

        return tools

    def configure(self, odr_config: ODRConfig) -> None:
        """Configure les parametres de diffusion"""
        self.odr_config = odr_config
        logger.info(f"Configuration ODR: {odr_config.frequency_mhz} MHz, "
                   f"{odr_config.output_power_dbm} dBm")

    def set_channel(self, channel: str) -> bool:
        """Configure la frequence par nom de canal"""
        if channel in self.FRANCE_CHANNELS:
            self.odr_config.frequency_mhz = self.FRANCE_CHANNELS[channel]
            logger.info(f"Canal configure: {channel} ({self.odr_config.frequency_mhz} MHz)")
            return True
        else:
            logger.error(f"Canal inconnu: {channel}")
            return False

    def generate_mux_config(self) -> str:
        """Genere la configuration ODR-DabMux"""
        config_path = self.config_dir / "dabmux.mux"
        dab = self.config.dab

        config_content = f"""; Configuration ODR-DabMux pour RadioLM
; Generee par DAB+ Podcast Streamer
; Date: {datetime.now().isoformat()}

general {{
    dabmode {self.odr_config.transmission_mode.value}
    nbframes 0
    syslog false
    tist false
    managementport 12720
}}

remotecontrol {{
    telnetport 12721
    zmqendpoint tcp://127.0.0.1:12722
}}

ensemble {{
    id {dab.ensemble_id}
    ecc {dab.ensemble_ecc}
    local-time-offset auto
    international-table 1
    label "{dab.ensemble_label}"
    shortlabel "{dab.ensemble_label[:8]}"
}}

services {{
    srv-radiolm {{
        id {dab.service_id}
        label "{dab.service_label}"
        shortlabel "{dab.service_label[:8]}"
        pty 0
        language 0x08
    }}
}}

subchannels {{
    sub-radiolm {{
        type dabplus
        inputproto zmq
        inputuri {self.odr_config.zmq_audio_input}
        zmq-buffer 40
        zmq-prebuffering 20
        bitrate {dab.bitrate}
        id {dab.subchannel_id}
        protection {dab.protection_level}
    }}
}}

components {{
    comp-radiolm {{
        service srv-radiolm
        subchannel sub-radiolm
        user-applications {{
            userapp "slideshow"
        }}
    }}
}}

outputs {{
    zmq "tcp://*:9100"
    throttle "simul://"
}}
"""

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        logger.info(f"Configuration MUX generee: {config_path}")
        return str(config_path)

    def generate_mod_config(self) -> str:
        """Genere la configuration ODR-DabMod"""
        config_path = self.config_dir / "dabmod.ini"

        # Determiner la configuration de sortie
        output_section = self._get_output_section()

        config_content = f"""; Configuration ODR-DabMod pour RadioLM
; Generee par DAB+ Podcast Streamer
; Date: {datetime.now().isoformat()}
;
; ATTENTION: Respectez la reglementation radio!

[remotecontrol]
telnet=1
telnetport=12723
zmqctrl=1
zmqctrlendpoint=tcp://127.0.0.1:12724

[log]
syslog=0
filelog=0
filename=/tmp/dabmod.log

[input]
transport=zmq
source={self.odr_config.zmq_mux_output}
max_frames_queued=100

[modulator]
gainmode=var
digital_gain={self.odr_config.digital_gain}
rate=2048000
dac_clk_rate=0
ofdmwindowing=0

[firfilter]
enabled=0

[poly]
enabled=0

{output_section}
"""

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        logger.info(f"Configuration MOD generee: {config_path}")
        return str(config_path)

    def _get_output_section(self) -> str:
        """Genere la section output selon le type de sortie"""
        oc = self.odr_config

        if oc.output_type == OutputType.FILE:
            return f"""[output]
output=file
filename=./output.iq
format=s16"""

        elif oc.output_type == OutputType.SOAPYSDR:
            return f"""[output]
output=soapysdr
device={oc.sdr_device}
channel={oc.sdr_channel}
txgain={oc.sdr_gain}
frequency={oc.frequency_mhz}e6
antenna={oc.sdr_antenna}
lo_offset=0"""

        elif oc.output_type == OutputType.LIMESDR:
            return f"""[output]
output=limesdr
device=
txgain={oc.sdr_gain}
frequency={oc.frequency_mhz}e6
bandwidth=2.5e6
channel={oc.sdr_channel}
antenna={oc.sdr_antenna}"""

        elif oc.output_type == OutputType.UHDHACKRF:
            return f"""[output]
output=uhd
device=
txgain={oc.sdr_gain}
frequency={oc.frequency_mhz}e6
channel={oc.sdr_channel}
refclk_source=internal"""

        elif oc.output_type == OutputType.ZMQ:
            return f"""[output]
output=zmq
zmq_output=tcp://*:9200
zmq_proto=epgm"""

        return ""

    def start_encoder(self, audio_source: str) -> bool:
        """
        Demarre l'encodeur audio ODR-AudioEnc

        Args:
            audio_source: Chemin du fichier ou "alsa:default" pour entree audio

        Returns:
            True si l'encodeur a demarre
        """
        if not self.odr_tools_available.get("odr-audioenc", False):
            logger.warning("ODR-AudioEnc non disponible, utilisation de FFmpeg")
            return self._start_ffmpeg_encoder(audio_source)

        oc = self.odr_config
        dab = self.config.dab

        # Creer le FIFO PAD si necessaire
        pad_args = []
        if oc.enable_pad:
            pad_fifo = self.config_dir / "pad.fifo"
            if not pad_fifo.exists():
                os.mkfifo(pad_fifo)
            pad_args = ["-P", str(pad_fifo)]

        # Construire la commande
        cmd = [
            oc.odr_audioenc_path,
            "-b", str(dab.bitrate),
            "-r", str(dab.sample_rate),
            "-c", str(dab.channels),
            "-o", oc.zmq_audio_input,
            "-p", "48",  # Padding
            *pad_args,
        ]

        # Source audio
        if audio_source.startswith("alsa:"):
            cmd.extend(["-d", audio_source.replace("alsa:", "")])
        elif audio_source.startswith("jack"):
            cmd.extend(["-j", audio_source])
        else:
            # Fichier via stdin pipe
            cmd.extend(["-i", "-"])

        try:
            if audio_source.startswith(("alsa:", "jack")):
                self.encoder_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                # Pipe depuis FFmpeg pour fichiers
                ffmpeg_cmd = [
                    self.config.encoder.ffmpeg_path,
                    "-re",
                    "-i", audio_source,
                    "-ar", str(dab.sample_rate),
                    "-ac", str(dab.channels),
                    "-f", "s16le",
                    "-"
                ]
                ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self.encoder_process = subprocess.Popen(
                    cmd,
                    stdin=ffmpeg_proc.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            self.status.encoder_running = True
            logger.info("ODR-AudioEnc demarre")
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur demarrage encodeur: {e}")
            return False

    def _start_ffmpeg_encoder(self, audio_source: str) -> bool:
        """Encodeur FFmpeg comme alternative a ODR-AudioEnc"""
        oc = self.odr_config
        dab = self.config.dab

        cmd = [
            self.config.encoder.ffmpeg_path,
            "-re",
            "-i", audio_source,
            "-ar", str(dab.sample_rate),
            "-ac", str(dab.channels),
            "-c:a", "libfdk_aac",
            "-profile:a", "aac_he_v2",
            "-b:a", f"{dab.bitrate}k",
            "-f", "adts",
            "-"
        ]

        try:
            # Utiliser un wrapper pour envoyer vers ZMQ
            # (simplification - en production utiliser odr-zmq2edi ou similaire)
            self.encoder_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self.status.encoder_running = True
            logger.info("Encodeur FFmpeg demarre (fallback)")
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur demarrage encodeur FFmpeg: {e}")
            return False

    def start_pad_encoder(self, dls_text: str = "") -> bool:
        """
        Demarre l'encodeur PAD pour Dynamic Label et Slideshow

        Args:
            dls_text: Texte initial du Dynamic Label

        Returns:
            True si l'encodeur PAD a demarre
        """
        if not self.odr_tools_available.get("odr-padenc", False):
            logger.warning("ODR-PadEnc non disponible")
            return False

        oc = self.odr_config
        pad_fifo = self.config_dir / "pad.fifo"
        slide_dir = self.config_dir / "slides"

        # Creer le fichier DLS
        dls_file = self.config_dir / "dls.txt"
        with open(dls_file, "w") as f:
            f.write(dls_text or f"RadioLM - {datetime.now().strftime('%H:%M')}")

        cmd = [
            oc.odr_padenc_path,
            "-o", str(pad_fifo),
            "-t", str(dls_file),
            "-s", str(slide_dir),
            "-p", "58",  # Pad size
        ]

        try:
            self.pad_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info("ODR-PadEnc demarre")
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur demarrage PAD: {e}")
            return False

    def start_multiplexer(self) -> bool:
        """Demarre ODR-DabMux"""
        if not self.odr_tools_available.get("odr-dabmux", False):
            logger.error("ODR-DabMux non disponible")
            return False

        # Generer la configuration
        config_path = self.generate_mux_config()

        cmd = [self.odr_config.odr_dabmux_path, config_path]

        try:
            self.mux_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.status.mux_running = True
            logger.info("ODR-DabMux demarre")
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur demarrage MUX: {e}")
            return False

    def start_modulator(self) -> bool:
        """Demarre ODR-DabMod"""
        if not self.odr_tools_available.get("odr-dabmod", False):
            logger.error("ODR-DabMod non disponible")
            return False

        # Generer la configuration
        config_path = self.generate_mod_config()

        cmd = [self.odr_config.odr_dabmod_path, config_path]

        try:
            self.mod_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.status.mod_running = True
            self.status.frequency_mhz = self.odr_config.frequency_mhz
            self.status.output_power_dbm = self.odr_config.output_power_dbm
            logger.info(f"ODR-DabMod demarre sur {self.odr_config.frequency_mhz} MHz")
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur demarrage MOD: {e}")
            return False

    def start_broadcast(self, audio_source: str) -> bool:
        """
        Demarre la diffusion DAB+ complete

        ATTENTION: Verifiez que vous avez l'autorisation de diffuser!

        Args:
            audio_source: Source audio (fichier, alsa:device, jack)

        Returns:
            True si la diffusion a demarre
        """
        logger.info("=" * 50)
        logger.info("DEMARRAGE DIFFUSION DAB+ REELLE")
        logger.info(f"Frequence: {self.odr_config.frequency_mhz} MHz")
        logger.info(f"Puissance: {self.odr_config.output_power_dbm} dBm")
        logger.info("ATTENTION: Respectez la reglementation!")
        logger.info("=" * 50)

        # 1. Demarrer le multiplexeur
        if not self.start_multiplexer():
            return False
        time.sleep(1)

        # 2. Demarrer le modulateur
        if not self.start_modulator():
            self.stop_broadcast()
            return False
        time.sleep(1)

        # 3. Demarrer l'encodeur PAD (optionnel)
        if self.odr_config.enable_pad:
            self.start_pad_encoder()

        # 4. Demarrer l'encodeur audio
        if not self.start_encoder(audio_source):
            self.stop_broadcast()
            return False

        # Marquer comme en cours
        self.status.is_running = True
        self.status.started_at = datetime.now()

        # Demarrer le monitoring
        self._start_monitoring()

        logger.info("Diffusion DAB+ demarree avec succes!")
        return True

    def stop_broadcast(self) -> None:
        """Arrete la diffusion DAB+"""
        logger.info("Arret de la diffusion DAB+...")

        self._stop_event.set()

        # Arreter les processus dans l'ordre inverse
        for proc, name in [
            (self.encoder_process, "Encodeur"),
            (self.pad_process, "PAD"),
            (self.mod_process, "Modulateur"),
            (self.mux_process, "Multiplexeur"),
        ]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                    logger.info(f"{name} arrete")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    logger.warning(f"{name} force a s'arreter")

        self.encoder_process = None
        self.pad_process = None
        self.mod_process = None
        self.mux_process = None

        self.status.is_running = False
        self.status.mux_running = False
        self.status.mod_running = False
        self.status.encoder_running = False

        logger.info("Diffusion DAB+ arretee")

    def _start_monitoring(self) -> None:
        """Demarre le thread de surveillance"""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Boucle de surveillance des processus"""
        while not self._stop_event.is_set():
            # Verifier les processus
            if self.mux_process and self.mux_process.poll() is not None:
                self.status.mux_running = False
                self.status.last_error = "Multiplexeur arrete inopinement"
                if self.on_error:
                    self.on_error(self.status.last_error)

            if self.mod_process and self.mod_process.poll() is not None:
                self.status.mod_running = False
                self.status.last_error = "Modulateur arrete inopinement"
                if self.on_error:
                    self.on_error(self.status.last_error)

            # Mettre a jour l'uptime
            if self.status.started_at:
                delta = datetime.now() - self.status.started_at
                self.status.uptime_seconds = int(delta.total_seconds())

            if self.on_status_change:
                self.on_status_change(self.status)

            time.sleep(2)

    def update_dls(self, text: str) -> bool:
        """Met a jour le Dynamic Label Segment"""
        dls_file = self.config_dir / "dls.txt"
        try:
            with open(dls_file, "w") as f:
                f.write(text[:128])  # Max 128 caracteres
            logger.debug(f"DLS mis a jour: {text}")
            return True
        except OSError as e:
            logger.error(f"Erreur mise a jour DLS: {e}")
            return False

    def add_slide(self, image_path: str) -> bool:
        """Ajoute une image au slideshow MOT"""
        slide_dir = self.config_dir / "slides"
        try:
            import shutil
            dest = slide_dir / Path(image_path).name
            shutil.copy(image_path, dest)
            logger.info(f"Slide ajoute: {dest}")
            return True
        except (OSError, shutil.Error) as e:
            logger.error(f"Erreur ajout slide: {e}")
            return False

    def get_status(self) -> dict:
        """Retourne le status de la diffusion"""
        return {
            "is_running": self.status.is_running,
            "mux_running": self.status.mux_running,
            "mod_running": self.status.mod_running,
            "encoder_running": self.status.encoder_running,
            "frequency_mhz": self.status.frequency_mhz,
            "output_power_dbm": self.status.output_power_dbm,
            "uptime_seconds": self.status.uptime_seconds,
            "uptime_formatted": self._format_uptime(self.status.uptime_seconds),
            "last_error": self.status.last_error,
            "odr_tools": self.odr_tools_available,
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        """Formate l'uptime en HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @classmethod
    def get_available_channels(cls) -> dict[str, float]:
        """Retourne la liste des canaux DAB+ disponibles en France"""
        return cls.FRANCE_CHANNELS.copy()


class ODRInstaller:
    """
    Assistant d'installation des outils ODR

    Les outils ODR doivent etre compiles depuis les sources:
    https://github.com/Opendigitalradio
    """

    REPOS = {
        "odr-dabmux": "https://github.com/Opendigitalradio/ODR-DabMux.git",
        "odr-dabmod": "https://github.com/Opendigitalradio/ODR-DabMod.git",
        "odr-audioenc": "https://github.com/Opendigitalradio/ODR-AudioEnc.git",
        "odr-padenc": "https://github.com/Opendigitalradio/ODR-PadEnc.git",
    }

    @classmethod
    def get_install_instructions(cls) -> str:
        """Retourne les instructions d'installation"""
        return """
# Installation des outils Open Digital Radio (ODR)
# Documentation complete: https://www.opendigitalradio.org/

# 1. Installer les dependances (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y \\
    build-essential automake libtool pkg-config \\
    libzmq3-dev libzmq5 \\
    libfdk-aac-dev \\
    libcurl4-openssl-dev \\
    libmagickwand-dev \\
    libvlc-dev \\
    libsamplerate0-dev \\
    libasound2-dev \\
    libboost-all-dev \\
    libuhd-dev \\
    libsoapysdr-dev

# 2. Compiler et installer ODR-DabMux
git clone https://github.com/Opendigitalradio/ODR-DabMux.git
cd ODR-DabMux
./bootstrap
./configure
make
sudo make install
cd ..

# 3. Compiler et installer ODR-DabMod
git clone https://github.com/Opendigitalradio/ODR-DabMod.git
cd ODR-DabMod
./bootstrap
./configure --enable-limesdr
make
sudo make install
cd ..

# 4. Compiler et installer ODR-AudioEnc
git clone https://github.com/Opendigitalradio/ODR-AudioEnc.git
cd ODR-AudioEnc
./bootstrap
./configure
make
sudo make install
cd ..

# 5. Compiler et installer ODR-PadEnc
git clone https://github.com/Opendigitalradio/ODR-PadEnc.git
cd ODR-PadEnc
./bootstrap
./configure
make
sudo make install
cd ..

# 6. Verifier l'installation
odr-dabmux --help
odr-dabmod --help
odr-audioenc --help
odr-padenc --help
"""

    @classmethod
    def check_dependencies(cls) -> dict[str, bool]:
        """Verifie les dependances systeme"""
        deps = {}

        # Verifier les bibliotheques
        for lib in ["libzmq", "libfdk-aac", "libsoapysdr"]:
            try:
                result = subprocess.run(
                    ["pkg-config", "--exists", lib],
                    capture_output=True,
                )
                deps[lib] = result.returncode == 0
            except FileNotFoundError:
                deps[lib] = False

        return deps
