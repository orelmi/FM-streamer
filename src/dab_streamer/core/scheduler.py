"""
Broadcast Scheduler - Planification de la diffusion des podcasts
"""

import os
import json
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
import schedule

from .config import Config
from .podcast_manager import PodcastManager, Episode, Podcast
from .audio_encoder import AudioEncoder
from .dab_multiplexer import DABMultiplexer, DABStreamPlayer

logger = logging.getLogger(__name__)


class RepeatMode(Enum):
    """Mode de répétition pour les programmes"""
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    WEEKDAYS = "weekdays"
    WEEKEND = "weekend"


@dataclass
class ScheduledProgram:
    """Programme planifié"""
    id: str
    name: str
    podcast_id: str
    episode_id: Optional[str] = None  # Si None, joue le dernier épisode
    start_time: str = "08:00"  # Format HH:MM
    repeat_mode: RepeatMode = RepeatMode.DAILY
    days: list[int] = field(default_factory=list)  # 0=lundi, 6=dimanche
    enabled: bool = True
    priority: int = 0  # Plus élevé = plus prioritaire
    created: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "podcast_id": self.podcast_id,
            "episode_id": self.episode_id,
            "start_time": self.start_time,
            "repeat_mode": self.repeat_mode.value,
            "days": self.days,
            "enabled": self.enabled,
            "priority": self.priority,
            "created": self.created.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledProgram":
        return cls(
            id=data["id"],
            name=data["name"],
            podcast_id=data["podcast_id"],
            episode_id=data.get("episode_id"),
            start_time=data.get("start_time", "08:00"),
            repeat_mode=RepeatMode(data.get("repeat_mode", "daily")),
            days=data.get("days", []),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
            created=datetime.fromisoformat(data.get("created", datetime.now().isoformat())),
        )


@dataclass
class PlaylistItem:
    """Élément de playlist"""
    podcast: Podcast
    episode: Episode
    scheduled_time: Optional[datetime] = None
    program_id: Optional[str] = None


class BroadcastScheduler:
    """Planificateur de diffusion"""

    def __init__(
        self,
        config: Config,
        podcast_manager: PodcastManager,
        encoder: AudioEncoder,
        multiplexer: DABMultiplexer,
    ):
        self.config = config
        self.podcast_manager = podcast_manager
        self.encoder = encoder
        self.multiplexer = multiplexer

        # Programmes planifiés
        self.programs: dict[str, ScheduledProgram] = {}

        # Playlist active
        self.playlist: list[PlaylistItem] = []
        self.current_index: int = 0

        # Lecteur
        self.player = DABStreamPlayer(multiplexer, encoder)
        self.player.on_track_finished = self._on_track_finished

        # Service DAB+ actif
        self.service_id: Optional[str] = None

        # État
        self.is_running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Callbacks
        self.on_episode_start: Optional[Callable[[Podcast, Episode], None]] = None
        self.on_episode_end: Optional[Callable[[Podcast, Episode], None]] = None
        self.on_playlist_empty: Optional[Callable[[], None]] = None

        # Charger les programmes sauvegardés
        self.db_path = Path(config.data_dir) / "schedule.json"
        self._load_programs()

    def _load_programs(self) -> None:
        """Charge les programmes depuis le fichier"""
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for prog_data in data.get("programs", []):
                    program = ScheduledProgram.from_dict(prog_data)
                    self.programs[program.id] = program
                logger.info(f"Chargé {len(self.programs)} programmes planifiés")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Erreur de chargement des programmes: {e}")

    def _save_programs(self) -> None:
        """Sauvegarde les programmes"""
        data = {
            "programs": [p.to_dict() for p in self.programs.values()],
            "updated": datetime.now().isoformat(),
        }
        os.makedirs(self.db_path.parent, exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_program(self, program: ScheduledProgram) -> None:
        """Ajoute un programme planifié"""
        self.programs[program.id] = program
        self._save_programs()
        self._schedule_program(program)
        logger.info(f"Programme ajouté: {program.name} à {program.start_time}")

    def remove_program(self, program_id: str) -> bool:
        """Supprime un programme"""
        if program_id in self.programs:
            del self.programs[program_id]
            self._save_programs()
            schedule.clear(program_id)
            logger.info(f"Programme supprimé: {program_id}")
            return True
        return False

    def update_program(self, program: ScheduledProgram) -> None:
        """Met à jour un programme"""
        schedule.clear(program.id)
        self.programs[program.id] = program
        self._save_programs()
        self._schedule_program(program)
        logger.info(f"Programme mis à jour: {program.name}")

    def get_program(self, program_id: str) -> Optional[ScheduledProgram]:
        """Récupère un programme par son ID"""
        return self.programs.get(program_id)

    def get_all_programs(self) -> list[ScheduledProgram]:
        """Récupère tous les programmes"""
        return list(self.programs.values())

    def _schedule_program(self, program: ScheduledProgram) -> None:
        """Planifie un programme dans schedule"""
        if not program.enabled:
            return

        job_func = lambda: self._trigger_program(program.id)

        if program.repeat_mode == RepeatMode.ONCE:
            # Exécution unique
            schedule.every().day.at(program.start_time).do(job_func).tag(program.id)

        elif program.repeat_mode == RepeatMode.DAILY:
            schedule.every().day.at(program.start_time).do(job_func).tag(program.id)

        elif program.repeat_mode == RepeatMode.WEEKLY:
            for day in program.days:
                self._schedule_day(day, program.start_time, job_func, program.id)

        elif program.repeat_mode == RepeatMode.WEEKDAYS:
            for day in range(5):  # Lundi à vendredi
                self._schedule_day(day, program.start_time, job_func, program.id)

        elif program.repeat_mode == RepeatMode.WEEKEND:
            for day in [5, 6]:  # Samedi et dimanche
                self._schedule_day(day, program.start_time, job_func, program.id)

    def _schedule_day(
        self, day: int, time_str: str, job_func: Callable, tag: str
    ) -> None:
        """Planifie une tâche pour un jour spécifique"""
        days_map = {
            0: schedule.every().monday,
            1: schedule.every().tuesday,
            2: schedule.every().wednesday,
            3: schedule.every().thursday,
            4: schedule.every().friday,
            5: schedule.every().saturday,
            6: schedule.every().sunday,
        }
        if day in days_map:
            days_map[day].at(time_str).do(job_func).tag(tag)

    def _trigger_program(self, program_id: str) -> None:
        """Déclenche un programme planifié"""
        program = self.programs.get(program_id)
        if not program or not program.enabled:
            return

        logger.info(f"Déclenchement du programme: {program.name}")

        podcast = self.podcast_manager.get_podcast(program.podcast_id)
        if not podcast:
            logger.error(f"Podcast non trouvé: {program.podcast_id}")
            return

        # Déterminer l'épisode à jouer
        if program.episode_id:
            episode = self.podcast_manager.get_episode(
                program.podcast_id, program.episode_id
            )
        else:
            # Prendre le dernier épisode téléchargé
            downloaded = [ep for ep in podcast.episodes if ep.downloaded]
            episode = downloaded[0] if downloaded else None

        if not episode:
            logger.warning(f"Aucun épisode disponible pour {podcast.title}")
            return

        # Ajouter à la playlist
        self.add_to_playlist(podcast, episode, program_id=program.id)

        # Démarrer si pas en cours de lecture
        if not self.player.is_playing:
            self.play_next()

    def add_to_playlist(
        self,
        podcast: Podcast,
        episode: Episode,
        position: Optional[int] = None,
        program_id: Optional[str] = None,
    ) -> None:
        """Ajoute un épisode à la playlist"""
        item = PlaylistItem(
            podcast=podcast,
            episode=episode,
            program_id=program_id,
        )

        if position is None:
            self.playlist.append(item)
        else:
            self.playlist.insert(position, item)

        logger.info(f"Ajouté à la playlist: {episode.title}")

    def remove_from_playlist(self, index: int) -> bool:
        """Supprime un élément de la playlist"""
        if 0 <= index < len(self.playlist):
            removed = self.playlist.pop(index)
            if index < self.current_index:
                self.current_index -= 1
            logger.info(f"Retiré de la playlist: {removed.episode.title}")
            return True
        return False

    def clear_playlist(self) -> None:
        """Vide la playlist"""
        self.playlist.clear()
        self.current_index = 0
        logger.info("Playlist vidée")

    def get_playlist(self) -> list[dict]:
        """Retourne la playlist actuelle"""
        return [
            {
                "index": i,
                "podcast_title": item.podcast.title,
                "episode_title": item.episode.title,
                "duration": item.episode.duration,
                "is_current": i == self.current_index,
            }
            for i, item in enumerate(self.playlist)
        ]

    def play_next(self) -> bool:
        """Joue l'élément suivant de la playlist"""
        if not self.service_id:
            logger.error("Aucun service DAB+ configuré")
            return False

        if self.current_index >= len(self.playlist):
            logger.info("Fin de la playlist")
            if self.on_playlist_empty:
                self.on_playlist_empty()
            return False

        item = self.playlist[self.current_index]
        episode = item.episode

        # Vérifier que l'épisode est téléchargé
        if not episode.downloaded or not episode.local_path:
            logger.warning(f"Épisode non téléchargé: {episode.title}")
            self.current_index += 1
            return self.play_next()

        # Vérifier si l'épisode est encodé pour DAB+
        audio_path = episode.local_path
        if episode.encoded_path and os.path.exists(episode.encoded_path):
            audio_path = episode.encoded_path
        else:
            # Encoder l'épisode
            result = self.encoder.encode_file(episode.local_path)
            if result.success:
                episode.encoded_path = result.output_path
                audio_path = result.output_path
            else:
                logger.error(f"Erreur d'encodage: {result.error_message}")

        # Mettre à jour le PAD
        self.multiplexer.update_pad(
            self.service_id,
            dls_text=f"{item.podcast.title} - {episode.title}",
        )

        # Callback de début
        if self.on_episode_start:
            self.on_episode_start(item.podcast, episode)

        # Lancer la lecture
        success = self.player.play(audio_path, self.service_id)

        if success:
            logger.info(f"Lecture: {episode.title}")

        return success

    def _on_track_finished(self, audio_file: str) -> None:
        """Callback appelé quand une piste est terminée"""
        if self.current_index < len(self.playlist):
            item = self.playlist[self.current_index]
            if self.on_episode_end:
                self.on_episode_end(item.podcast, item.episode)

        self.current_index += 1
        self.play_next()

    def play(self) -> bool:
        """Démarre la lecture"""
        if not self.playlist:
            logger.warning("Playlist vide")
            return False
        return self.play_next()

    def pause(self) -> None:
        """Met en pause la lecture"""
        self.player.stop()
        logger.info("Lecture en pause")

    def stop(self) -> None:
        """Arrête la lecture et réinitialise"""
        self.player.stop()
        self.current_index = 0
        logger.info("Lecture arrêtée")

    def skip(self) -> bool:
        """Passe à l'élément suivant"""
        self.player.stop()
        self.current_index += 1
        return self.play_next()

    def previous(self) -> bool:
        """Revient à l'élément précédent"""
        self.player.stop()
        if self.current_index > 0:
            self.current_index -= 1
        return self.play_next()

    def start(self, service_id: str) -> None:
        """Démarre le scheduler"""
        self.service_id = service_id
        self.is_running = True
        self._stop_event.clear()

        # Planifier tous les programmes
        for program in self.programs.values():
            self._schedule_program(program)

        # Démarrer le thread du scheduler
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop)
        self._scheduler_thread.daemon = True
        self._scheduler_thread.start()

        logger.info("Scheduler démarré")

    def _scheduler_loop(self) -> None:
        """Boucle principale du scheduler"""
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    def shutdown(self) -> None:
        """Arrête le scheduler"""
        self._stop_event.set()
        self.player.stop()

        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None

        schedule.clear()
        self.is_running = False
        logger.info("Scheduler arrêté")

    def get_status(self) -> dict:
        """Retourne l'état actuel du scheduler"""
        current_item = None
        if self.current_index < len(self.playlist):
            item = self.playlist[self.current_index]
            current_item = {
                "podcast": item.podcast.title,
                "episode": item.episode.title,
                "duration": item.episode.duration,
            }

        return {
            "running": self.is_running,
            "playing": self.player.is_playing,
            "service_id": self.service_id,
            "playlist_length": len(self.playlist),
            "current_index": self.current_index,
            "current_item": current_item,
            "programs_count": len(self.programs),
        }

    def auto_fill_playlist(self, hours: int = 4) -> int:
        """
        Remplit automatiquement la playlist avec des épisodes

        Args:
            hours: Nombre d'heures de contenu à prévoir

        Returns:
            Nombre d'épisodes ajoutés
        """
        target_duration = hours * 3600  # En secondes
        current_duration = sum(
            item.episode.duration for item in self.playlist[self.current_index:]
        )

        added = 0
        downloaded_episodes = self.podcast_manager.get_downloaded_episodes()

        for podcast, episode in downloaded_episodes:
            if current_duration >= target_duration:
                break

            # Vérifier si l'épisode n'est pas déjà dans la playlist
            already_in = any(
                item.episode.id == episode.id for item in self.playlist
            )

            if not already_in:
                self.add_to_playlist(podcast, episode)
                current_duration += episode.duration
                added += 1

        logger.info(f"Playlist remplie avec {added} épisodes")
        return added

    def shuffle_playlist(self) -> None:
        """Mélange la playlist (après l'index courant)"""
        import random

        if self.current_index < len(self.playlist) - 1:
            remaining = self.playlist[self.current_index + 1:]
            random.shuffle(remaining)
            self.playlist = self.playlist[:self.current_index + 1] + remaining
            logger.info("Playlist mélangée")
