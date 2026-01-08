"""
Podcast Manager - Gestion des podcasts et flux RSS
"""

import os
import json
import hashlib
import logging
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
import feedparser
import requests
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from .config import Config, PodcastConfig

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """Représente un épisode de podcast"""
    id: str
    podcast_id: str
    title: str
    description: str
    url: str
    duration: int  # en secondes
    published: datetime
    downloaded: bool = False
    local_path: Optional[str] = None
    encoded_path: Optional[str] = None
    file_size: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["published"] = self.published.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Episode":
        data["published"] = datetime.fromisoformat(data["published"])
        return cls(**data)


@dataclass
class Podcast:
    """Représente un podcast"""
    id: str
    title: str
    feed_url: str
    description: str = ""
    author: str = ""
    image_url: str = ""
    website: str = ""
    language: str = "fr"
    last_updated: Optional[datetime] = None
    episodes: list[Episode] = None

    def __post_init__(self):
        if self.episodes is None:
            self.episodes = []

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "title": self.title,
            "feed_url": self.feed_url,
            "description": self.description,
            "author": self.author,
            "image_url": self.image_url,
            "website": self.website,
            "language": self.language,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "episodes": [ep.to_dict() for ep in self.episodes],
        }
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Podcast":
        episodes = [Episode.from_dict(ep) for ep in data.get("episodes", [])]
        last_updated = None
        if data.get("last_updated"):
            last_updated = datetime.fromisoformat(data["last_updated"])
        return cls(
            id=data["id"],
            title=data["title"],
            feed_url=data["feed_url"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            image_url=data.get("image_url", ""),
            website=data.get("website", ""),
            language=data.get("language", "fr"),
            last_updated=last_updated,
            episodes=episodes,
        )


class PodcastManager:
    """Gestionnaire de podcasts"""

    def __init__(self, config: Config):
        self.config = config
        self.podcast_config = config.podcast
        self.podcasts: dict[str, Podcast] = {}
        self.db_path = Path(config.data_dir) / "podcasts.json"
        self._load_db()

    def _load_db(self) -> None:
        """Charge la base de données des podcasts"""
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for podcast_data in data.get("podcasts", []):
                    podcast = Podcast.from_dict(podcast_data)
                    self.podcasts[podcast.id] = podcast
                logger.info(f"Chargé {len(self.podcasts)} podcasts depuis la base de données")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Erreur lors du chargement de la base de données: {e}")
                self.podcasts = {}

    def _save_db(self) -> None:
        """Sauvegarde la base de données des podcasts"""
        data = {
            "podcasts": [p.to_dict() for p in self.podcasts.values()],
            "updated": datetime.now().isoformat(),
        }
        os.makedirs(self.db_path.parent, exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _generate_id(url: str) -> str:
        """Génère un ID unique basé sur l'URL"""
        return hashlib.sha256(url.encode()).hexdigest()[:12]

    def add_podcast(self, feed_url: str) -> Podcast:
        """Ajoute un nouveau podcast depuis son flux RSS"""
        logger.info(f"Ajout du podcast: {feed_url}")

        # Parser le flux RSS
        feed = feedparser.parse(feed_url)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Flux RSS invalide: {feed_url}")

        podcast_id = self._generate_id(feed_url)

        # Extraire les informations du podcast
        podcast = Podcast(
            id=podcast_id,
            title=feed.feed.get("title", "Podcast sans titre"),
            feed_url=feed_url,
            description=feed.feed.get("description", ""),
            author=feed.feed.get("author", feed.feed.get("itunes_author", "")),
            image_url=self._get_image_url(feed),
            website=feed.feed.get("link", ""),
            language=feed.feed.get("language", "fr"),
            last_updated=datetime.now(),
        )

        # Extraire les épisodes
        for entry in feed.entries[:self.podcast_config.max_episodes]:
            episode = self._parse_episode(entry, podcast_id)
            if episode:
                podcast.episodes.append(episode)

        self.podcasts[podcast_id] = podcast
        self._save_db()

        logger.info(f"Podcast ajouté: {podcast.title} ({len(podcast.episodes)} épisodes)")
        return podcast

    def _get_image_url(self, feed) -> str:
        """Extrait l'URL de l'image du podcast"""
        if hasattr(feed.feed, "image") and feed.feed.image:
            return feed.feed.image.get("href", "")
        if hasattr(feed.feed, "itunes_image"):
            return feed.feed.itunes_image.get("href", "")
        return ""

    def _parse_episode(self, entry: dict, podcast_id: str) -> Optional[Episode]:
        """Parse un épisode depuis une entrée RSS"""
        # Trouver l'URL audio
        audio_url = None
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/"):
                audio_url = enclosure.get("href") or enclosure.get("url")
                break

        if not audio_url:
            # Essayer les liens
            for link in entry.get("links", []):
                if link.get("type", "").startswith("audio/"):
                    audio_url = link.get("href")
                    break

        if not audio_url:
            return None

        # Parser la date de publication
        published = datetime.now()
        if entry.get("published_parsed"):
            try:
                published = datetime(*entry.published_parsed[:6])
            except (TypeError, ValueError):
                pass

        # Durée de l'épisode
        duration = 0
        if entry.get("itunes_duration"):
            duration = self._parse_duration(entry.itunes_duration)

        episode_id = self._generate_id(audio_url)

        return Episode(
            id=episode_id,
            podcast_id=podcast_id,
            title=entry.get("title", "Episode sans titre"),
            description=entry.get("summary", entry.get("description", "")),
            url=audio_url,
            duration=duration,
            published=published,
        )

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse une durée au format HH:MM:SS ou secondes"""
        if not duration_str:
            return 0

        try:
            # Format secondes
            if duration_str.isdigit():
                return int(duration_str)

            # Format HH:MM:SS ou MM:SS
            parts = duration_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            pass

        return 0

    def remove_podcast(self, podcast_id: str) -> bool:
        """Supprime un podcast"""
        if podcast_id not in self.podcasts:
            return False

        podcast = self.podcasts[podcast_id]

        # Supprimer les fichiers téléchargés
        for episode in podcast.episodes:
            if episode.local_path and os.path.exists(episode.local_path):
                os.remove(episode.local_path)
            if episode.encoded_path and os.path.exists(episode.encoded_path):
                os.remove(episode.encoded_path)

        del self.podcasts[podcast_id]
        self._save_db()

        logger.info(f"Podcast supprimé: {podcast.title}")
        return True

    def refresh_podcast(self, podcast_id: str) -> Optional[Podcast]:
        """Rafraîchit un podcast depuis son flux RSS"""
        if podcast_id not in self.podcasts:
            return None

        podcast = self.podcasts[podcast_id]
        feed = feedparser.parse(podcast.feed_url)

        if feed.bozo and not feed.entries:
            logger.error(f"Erreur lors du rafraîchissement: {podcast.feed_url}")
            return None

        existing_ids = {ep.id for ep in podcast.episodes}
        new_episodes = []

        for entry in feed.entries[:self.podcast_config.max_episodes]:
            episode = self._parse_episode(entry, podcast_id)
            if episode and episode.id not in existing_ids:
                new_episodes.append(episode)

        podcast.episodes = new_episodes + podcast.episodes
        podcast.episodes = podcast.episodes[:self.podcast_config.max_episodes]
        podcast.last_updated = datetime.now()

        self._save_db()

        logger.info(f"Podcast rafraîchi: {podcast.title} ({len(new_episodes)} nouveaux épisodes)")
        return podcast

    def refresh_all(self) -> dict[str, int]:
        """Rafraîchit tous les podcasts"""
        results = {}
        for podcast_id in self.podcasts:
            podcast = self.refresh_podcast(podcast_id)
            if podcast:
                results[podcast.title] = len(
                    [ep for ep in podcast.episodes if not ep.downloaded]
                )
        return results

    async def download_episode(self, podcast_id: str, episode_id: str) -> Optional[str]:
        """Télécharge un épisode"""
        if podcast_id not in self.podcasts:
            return None

        podcast = self.podcasts[podcast_id]
        episode = next((ep for ep in podcast.episodes if ep.id == episode_id), None)

        if not episode:
            return None

        if episode.downloaded and episode.local_path and os.path.exists(episode.local_path):
            return episode.local_path

        # Créer le répertoire de téléchargement
        download_dir = Path(self.podcast_config.download_dir) / podcast_id
        os.makedirs(download_dir, exist_ok=True)

        # Déterminer l'extension
        ext = self._get_extension(episode.url)
        local_path = download_dir / f"{episode.id}{ext}"

        logger.info(f"Téléchargement: {episode.title}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(episode.url) as response:
                    if response.status != 200:
                        logger.error(f"Erreur HTTP {response.status}: {episode.url}")
                        return None

                    with open(local_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            episode.downloaded = True
            episode.local_path = str(local_path)
            episode.file_size = os.path.getsize(local_path)

            # Obtenir la durée si non définie
            if episode.duration == 0:
                episode.duration = self._get_audio_duration(local_path)

            self._save_db()

            logger.info(f"Téléchargement terminé: {episode.title}")
            return str(local_path)

        except (aiohttp.ClientError, OSError) as e:
            logger.error(f"Erreur de téléchargement: {e}")
            return None

    def download_episode_sync(self, podcast_id: str, episode_id: str) -> Optional[str]:
        """Télécharge un épisode (version synchrone)"""
        return asyncio.run(self.download_episode(podcast_id, episode_id))

    async def download_all_episodes(self, podcast_id: str) -> list[str]:
        """Télécharge tous les épisodes d'un podcast"""
        if podcast_id not in self.podcasts:
            return []

        podcast = self.podcasts[podcast_id]
        downloaded = []

        for episode in podcast.episodes:
            if not episode.downloaded:
                path = await self.download_episode(podcast_id, episode.id)
                if path:
                    downloaded.append(path)

        return downloaded

    @staticmethod
    def _get_extension(url: str) -> str:
        """Détermine l'extension du fichier depuis l'URL"""
        url_path = url.split("?")[0]
        if url_path.endswith(".mp3"):
            return ".mp3"
        elif url_path.endswith(".m4a") or url_path.endswith(".mp4"):
            return ".m4a"
        elif url_path.endswith(".ogg"):
            return ".ogg"
        elif url_path.endswith(".wav"):
            return ".wav"
        return ".mp3"  # Par défaut

    @staticmethod
    def _get_audio_duration(file_path: Path) -> int:
        """Obtient la durée d'un fichier audio en secondes"""
        try:
            ext = str(file_path).lower()
            if ext.endswith(".mp3"):
                audio = MP3(file_path)
            elif ext.endswith((".m4a", ".mp4", ".aac")):
                audio = MP4(file_path)
            elif ext.endswith(".ogg"):
                audio = OggVorbis(file_path)
            else:
                return 0
            return int(audio.info.length)
        except Exception:
            return 0

    def cleanup_old_episodes(self) -> int:
        """Nettoie les anciens épisodes téléchargés"""
        if not self.podcast_config.auto_cleanup:
            return 0

        cutoff = datetime.now() - timedelta(days=self.podcast_config.cleanup_days)
        removed = 0

        for podcast in self.podcasts.values():
            for episode in podcast.episodes:
                if episode.downloaded and episode.published < cutoff:
                    if episode.local_path and os.path.exists(episode.local_path):
                        os.remove(episode.local_path)
                        removed += 1
                    if episode.encoded_path and os.path.exists(episode.encoded_path):
                        os.remove(episode.encoded_path)
                    episode.downloaded = False
                    episode.local_path = None
                    episode.encoded_path = None

        self._save_db()
        logger.info(f"Nettoyage: {removed} fichiers supprimés")
        return removed

    def get_podcast(self, podcast_id: str) -> Optional[Podcast]:
        """Récupère un podcast par son ID"""
        return self.podcasts.get(podcast_id)

    def get_all_podcasts(self) -> list[Podcast]:
        """Récupère tous les podcasts"""
        return list(self.podcasts.values())

    def get_episode(self, podcast_id: str, episode_id: str) -> Optional[Episode]:
        """Récupère un épisode par son ID"""
        podcast = self.podcasts.get(podcast_id)
        if not podcast:
            return None
        return next((ep for ep in podcast.episodes if ep.id == episode_id), None)

    def get_downloaded_episodes(self) -> list[tuple[Podcast, Episode]]:
        """Récupère tous les épisodes téléchargés"""
        result = []
        for podcast in self.podcasts.values():
            for episode in podcast.episodes:
                if episode.downloaded and episode.local_path:
                    result.append((podcast, episode))
        return result

    def search_episodes(self, query: str) -> list[tuple[Podcast, Episode]]:
        """Recherche des épisodes par titre ou description"""
        query = query.lower()
        results = []
        for podcast in self.podcasts.values():
            for episode in podcast.episodes:
                if query in episode.title.lower() or query in episode.description.lower():
                    results.append((podcast, episode))
        return results
