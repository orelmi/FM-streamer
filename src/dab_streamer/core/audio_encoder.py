"""
Audio Encoder - Encodage audio pour DAB+ (HE-AAC)
"""

import os
import subprocess
import logging
import shutil
from pathlib import Path
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from .config import Config, EncoderConfig

logger = logging.getLogger(__name__)


class AudioCodec(Enum):
    """Codecs audio supportés pour DAB+"""
    AAC_LC = "aac-lc"
    HE_AAC_V1 = "he-aacv1"
    HE_AAC_V2 = "he-aacv2"


@dataclass
class EncodingResult:
    """Résultat d'un encodage"""
    success: bool
    input_path: str
    output_path: str
    codec: str
    bitrate: int
    duration: float
    error_message: str = ""


class AudioEncoder:
    """Encodeur audio pour DAB+"""

    # Bitrates recommandés pour DAB+ selon le codec
    RECOMMENDED_BITRATES = {
        AudioCodec.AAC_LC: [64, 80, 96, 128, 160, 192],
        AudioCodec.HE_AAC_V1: [32, 40, 48, 56, 64, 80],
        AudioCodec.HE_AAC_V2: [24, 32, 40, 48, 56, 64],
    }

    def __init__(self, config: Config):
        self.config = config
        self.encoder_config = config.encoder
        self.output_dir = Path(config.data_dir) / "encoded"
        os.makedirs(self.output_dir, exist_ok=True)

        # Vérifier les outils disponibles
        self.ffmpeg_available = self._check_ffmpeg()
        self.odr_audioenc_available = self._check_odr_audioenc()

        if not self.ffmpeg_available:
            logger.warning("FFmpeg non trouvé - encodage limité")

    def _check_ffmpeg(self) -> bool:
        """Vérifie si FFmpeg est disponible"""
        try:
            result = subprocess.run(
                [self.encoder_config.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _check_odr_audioenc(self) -> bool:
        """Vérifie si ODR-AudioEnc est disponible"""
        try:
            result = subprocess.run(
                [self.encoder_config.odr_audioenc_path, "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def get_codec(self) -> AudioCodec:
        """Retourne le codec configuré"""
        codec_map = {
            "aac-lc": AudioCodec.AAC_LC,
            "he-aacv1": AudioCodec.HE_AAC_V1,
            "he-aacv2": AudioCodec.HE_AAC_V2,
        }
        return codec_map.get(self.encoder_config.codec, AudioCodec.HE_AAC_V2)

    def encode_file(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        codec: Optional[AudioCodec] = None,
        bitrate: Optional[int] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
    ) -> EncodingResult:
        """
        Encode un fichier audio pour DAB+

        Args:
            input_path: Chemin du fichier source
            output_path: Chemin de sortie (auto-généré si None)
            codec: Codec à utiliser (config par défaut si None)
            bitrate: Débit en kbps (config par défaut si None)
            sample_rate: Fréquence d'échantillonnage (config par défaut si None)
            channels: Nombre de canaux (config par défaut si None)

        Returns:
            EncodingResult avec le résultat de l'encodage
        """
        if codec is None:
            codec = self.get_codec()
        if bitrate is None:
            bitrate = self.encoder_config.bitrate
        if sample_rate is None:
            sample_rate = self.encoder_config.sample_rate
        if channels is None:
            channels = self.encoder_config.channels

        # Générer le chemin de sortie
        if output_path is None:
            input_name = Path(input_path).stem
            output_path = str(self.output_dir / f"{input_name}_dab.aac")

        logger.info(f"Encodage: {input_path} -> {output_path}")
        logger.info(f"Paramètres: codec={codec.value}, bitrate={bitrate}k, "
                   f"sample_rate={sample_rate}, channels={channels}")

        # Utiliser FFmpeg pour l'encodage
        if self.ffmpeg_available:
            return self._encode_with_ffmpeg(
                input_path, output_path, codec, bitrate, sample_rate, channels
            )
        else:
            return EncodingResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                codec=codec.value,
                bitrate=bitrate,
                duration=0,
                error_message="FFmpeg non disponible",
            )

    def _encode_with_ffmpeg(
        self,
        input_path: str,
        output_path: str,
        codec: AudioCodec,
        bitrate: int,
        sample_rate: int,
        channels: int,
    ) -> EncodingResult:
        """Encode avec FFmpeg"""

        # Construire la commande FFmpeg
        cmd = [
            self.encoder_config.ffmpeg_path,
            "-y",  # Écraser le fichier de sortie
            "-i", input_path,
            "-ar", str(sample_rate),
            "-ac", str(channels),
        ]

        # Paramètres spécifiques au codec
        if codec == AudioCodec.AAC_LC:
            cmd.extend([
                "-c:a", "aac",
                "-b:a", f"{bitrate}k",
            ])
        elif codec == AudioCodec.HE_AAC_V1:
            cmd.extend([
                "-c:a", "libfdk_aac",
                "-profile:a", "aac_he",
                "-b:a", f"{bitrate}k",
            ])
        elif codec == AudioCodec.HE_AAC_V2:
            cmd.extend([
                "-c:a", "libfdk_aac",
                "-profile:a", "aac_he_v2",
                "-b:a", f"{bitrate}k",
            ])

        # Format de sortie ADTS pour DAB+
        cmd.extend([
            "-f", "adts",
            output_path,
        ])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 heure max
            )

            if result.returncode != 0:
                # Essayer avec le codec AAC natif de FFmpeg si libfdk_aac échoue
                if "libfdk_aac" in " ".join(cmd):
                    logger.warning("libfdk_aac non disponible, utilisation du codec AAC natif")
                    return self._encode_with_native_aac(
                        input_path, output_path, bitrate, sample_rate, channels
                    )

                return EncodingResult(
                    success=False,
                    input_path=input_path,
                    output_path=output_path,
                    codec=codec.value,
                    bitrate=bitrate,
                    duration=0,
                    error_message=result.stderr,
                )

            # Obtenir la durée du fichier encodé
            duration = self._get_duration(output_path)

            logger.info(f"Encodage terminé: {output_path} ({duration:.1f}s)")

            return EncodingResult(
                success=True,
                input_path=input_path,
                output_path=output_path,
                codec=codec.value,
                bitrate=bitrate,
                duration=duration,
            )

        except subprocess.TimeoutExpired:
            return EncodingResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                codec=codec.value,
                bitrate=bitrate,
                duration=0,
                error_message="Timeout lors de l'encodage",
            )
        except subprocess.SubprocessError as e:
            return EncodingResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                codec=codec.value,
                bitrate=bitrate,
                duration=0,
                error_message=str(e),
            )

    def _encode_with_native_aac(
        self,
        input_path: str,
        output_path: str,
        bitrate: int,
        sample_rate: int,
        channels: int,
    ) -> EncodingResult:
        """Encode avec le codec AAC natif de FFmpeg (fallback)"""

        cmd = [
            self.encoder_config.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-c:a", "aac",
            "-b:a", f"{bitrate}k",
            "-f", "adts",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode != 0:
                return EncodingResult(
                    success=False,
                    input_path=input_path,
                    output_path=output_path,
                    codec="aac-native",
                    bitrate=bitrate,
                    duration=0,
                    error_message=result.stderr,
                )

            duration = self._get_duration(output_path)

            return EncodingResult(
                success=True,
                input_path=input_path,
                output_path=output_path,
                codec="aac-native",
                bitrate=bitrate,
                duration=duration,
            )

        except subprocess.SubprocessError as e:
            return EncodingResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                codec="aac-native",
                bitrate=bitrate,
                duration=0,
                error_message=str(e),
            )

    def _get_duration(self, file_path: str) -> float:
        """Obtient la durée d'un fichier audio avec FFprobe"""
        try:
            ffprobe_path = self.encoder_config.ffmpeg_path.replace("ffmpeg", "ffprobe")
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            return 0.0

    def encode_for_dab_stream(
        self,
        input_path: str,
        output_fifo: str,
        bitrate: Optional[int] = None,
    ) -> subprocess.Popen:
        """
        Lance un processus d'encodage continu vers un FIFO pour streaming DAB+

        Args:
            input_path: Chemin du fichier source
            output_fifo: Chemin du FIFO de sortie
            bitrate: Débit en kbps

        Returns:
            Processus FFmpeg
        """
        if bitrate is None:
            bitrate = self.encoder_config.bitrate

        codec = self.get_codec()

        cmd = [
            self.encoder_config.ffmpeg_path,
            "-re",  # Lire à vitesse réelle
            "-i", input_path,
            "-ar", str(self.encoder_config.sample_rate),
            "-ac", str(self.encoder_config.channels),
        ]

        # Configuration du codec
        if codec == AudioCodec.HE_AAC_V2:
            cmd.extend(["-c:a", "libfdk_aac", "-profile:a", "aac_he_v2"])
        elif codec == AudioCodec.HE_AAC_V1:
            cmd.extend(["-c:a", "libfdk_aac", "-profile:a", "aac_he"])
        else:
            cmd.extend(["-c:a", "aac"])

        cmd.extend([
            "-b:a", f"{bitrate}k",
            "-f", "adts",
            output_fifo,
        ])

        logger.info(f"Démarrage du stream d'encodage: {input_path}")

        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def normalize_audio(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        target_lufs: float = -23.0,
    ) -> Optional[str]:
        """
        Normalise le niveau audio selon EBU R128

        Args:
            input_path: Chemin du fichier source
            output_path: Chemin de sortie (auto-généré si None)
            target_lufs: Niveau cible en LUFS (défaut: -23 pour broadcast)

        Returns:
            Chemin du fichier normalisé ou None si erreur
        """
        if not self.ffmpeg_available:
            return None

        if output_path is None:
            input_name = Path(input_path).stem
            output_path = str(self.output_dir / f"{input_name}_normalized.wav")

        cmd = [
            self.encoder_config.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode == 0:
                logger.info(f"Audio normalisé: {output_path}")
                return output_path
            else:
                logger.error(f"Erreur de normalisation: {result.stderr}")
                return None

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur de normalisation: {e}")
            return None

    def convert_to_wav(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> Optional[str]:
        """
        Convertit un fichier audio en WAV PCM

        Args:
            input_path: Chemin du fichier source
            output_path: Chemin de sortie (auto-généré si None)
            sample_rate: Fréquence d'échantillonnage
            channels: Nombre de canaux

        Returns:
            Chemin du fichier WAV ou None si erreur
        """
        if not self.ffmpeg_available:
            return None

        if output_path is None:
            input_name = Path(input_path).stem
            output_path = str(self.output_dir / f"{input_name}.wav")

        cmd = [
            self.encoder_config.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-c:a", "pcm_s16le",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode == 0:
                return output_path
            else:
                logger.error(f"Erreur de conversion: {result.stderr}")
                return None

        except subprocess.SubprocessError as e:
            logger.error(f"Erreur de conversion: {e}")
            return None

    def get_audio_info(self, file_path: str) -> dict:
        """Obtient les informations d'un fichier audio"""
        if not self.ffmpeg_available:
            return {}

        try:
            ffprobe_path = self.encoder_config.ffmpeg_path.replace("ffmpeg", "ffprobe")
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                import json
                return json.loads(result.stdout)

        except (subprocess.SubprocessError, ValueError):
            pass

        return {}

    def check_tools(self) -> dict[str, bool]:
        """Vérifie la disponibilité des outils d'encodage"""
        return {
            "ffmpeg": self.ffmpeg_available,
            "odr-audioenc": self.odr_audioenc_available,
            "libfdk_aac": self._check_libfdk_aac(),
        }

    def _check_libfdk_aac(self) -> bool:
        """Vérifie si libfdk_aac est disponible dans FFmpeg"""
        if not self.ffmpeg_available:
            return False

        try:
            result = subprocess.run(
                [self.encoder_config.ffmpeg_path, "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "libfdk_aac" in result.stdout
        except subprocess.SubprocessError:
            return False
