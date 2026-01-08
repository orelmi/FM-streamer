"""
Tests for podcast manager module
"""

import os
import tempfile
import pytest
from datetime import datetime
from dab_streamer.core.config import Config
from dab_streamer.core.podcast_manager import (
    PodcastManager,
    Podcast,
    Episode,
)


class TestEpisode:
    """Tests for Episode class"""

    def test_episode_creation(self):
        """Test creating an episode"""
        episode = Episode(
            id="test123",
            podcast_id="podcast456",
            title="Test Episode",
            description="A test episode",
            url="https://example.com/episode.mp3",
            duration=3600,
            published=datetime.now(),
        )

        assert episode.id == "test123"
        assert episode.title == "Test Episode"
        assert episode.duration == 3600
        assert episode.downloaded is False

    def test_episode_to_dict(self):
        """Test converting episode to dict"""
        now = datetime.now()
        episode = Episode(
            id="test123",
            podcast_id="podcast456",
            title="Test Episode",
            description="A test episode",
            url="https://example.com/episode.mp3",
            duration=3600,
            published=now,
        )

        data = episode.to_dict()

        assert data["id"] == "test123"
        assert data["title"] == "Test Episode"
        assert "published" in data

    def test_episode_from_dict(self):
        """Test creating episode from dict"""
        data = {
            "id": "test123",
            "podcast_id": "podcast456",
            "title": "Test Episode",
            "description": "A test episode",
            "url": "https://example.com/episode.mp3",
            "duration": 3600,
            "published": "2024-01-01T12:00:00",
            "downloaded": True,
            "local_path": "/path/to/file.mp3",
            "encoded_path": None,
            "file_size": 1024,
        }

        episode = Episode.from_dict(data)

        assert episode.id == "test123"
        assert episode.downloaded is True
        assert episode.published.year == 2024


class TestPodcast:
    """Tests for Podcast class"""

    def test_podcast_creation(self):
        """Test creating a podcast"""
        podcast = Podcast(
            id="podcast123",
            title="Test Podcast",
            feed_url="https://example.com/feed.xml",
        )

        assert podcast.id == "podcast123"
        assert podcast.title == "Test Podcast"
        assert podcast.episodes == []

    def test_podcast_to_dict(self):
        """Test converting podcast to dict"""
        podcast = Podcast(
            id="podcast123",
            title="Test Podcast",
            feed_url="https://example.com/feed.xml",
            author="Test Author",
        )

        data = podcast.to_dict()

        assert data["id"] == "podcast123"
        assert data["author"] == "Test Author"
        assert data["episodes"] == []


class TestPodcastManager:
    """Tests for PodcastManager class"""

    def test_manager_creation(self):
        """Test creating podcast manager"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.data_dir = os.path.join(tmpdir, "data")
            config.podcast.download_dir = os.path.join(tmpdir, "podcasts")

            manager = PodcastManager(config)

            assert len(manager.podcasts) == 0
            assert os.path.exists(config.data_dir)

    def test_generate_id(self):
        """Test ID generation"""
        id1 = PodcastManager._generate_id("https://example.com/feed1.xml")
        id2 = PodcastManager._generate_id("https://example.com/feed2.xml")
        id3 = PodcastManager._generate_id("https://example.com/feed1.xml")

        assert id1 != id2
        assert id1 == id3  # Same URL should give same ID
        assert len(id1) == 12

    def test_parse_duration(self):
        """Test duration parsing"""
        # Seconds
        assert PodcastManager._parse_duration("3600") == 3600

        # MM:SS
        assert PodcastManager._parse_duration("60:00") == 3600

        # HH:MM:SS
        assert PodcastManager._parse_duration("1:00:00") == 3600

        # Invalid
        assert PodcastManager._parse_duration("invalid") == 0
        assert PodcastManager._parse_duration("") == 0

    def test_get_extension(self):
        """Test file extension detection"""
        assert PodcastManager._get_extension("https://example.com/file.mp3") == ".mp3"
        assert PodcastManager._get_extension("https://example.com/file.m4a") == ".m4a"
        assert PodcastManager._get_extension("https://example.com/file.ogg") == ".ogg"
        assert PodcastManager._get_extension("https://example.com/file.mp3?token=123") == ".mp3"
        assert PodcastManager._get_extension("https://example.com/file") == ".mp3"  # Default
