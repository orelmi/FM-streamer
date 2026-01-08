"""
Tests for configuration module
"""

import os
import tempfile
import pytest
from dab_streamer.core.config import Config, DABConfig, EncoderConfig, PodcastConfig


class TestDABConfig:
    """Tests for DABConfig"""

    def test_default_values(self):
        """Test default configuration values"""
        config = DABConfig()

        assert config.ensemble_label == "RadioLM"
        assert config.service_label == "RadioLM"
        assert config.ensemble_ecc == "0xE1"  # France
        assert config.bitrate == 64
        assert config.sample_rate == 48000
        assert config.channels == 2


class TestEncoderConfig:
    """Tests for EncoderConfig"""

    def test_default_codec(self):
        """Test default codec is HE-AACv2"""
        config = EncoderConfig()

        assert config.codec == "he-aacv2"
        assert config.bitrate == 64


class TestPodcastConfig:
    """Tests for PodcastConfig"""

    def test_default_values(self):
        """Test default podcast configuration"""
        config = PodcastConfig()

        assert config.max_episodes == 10
        assert config.auto_cleanup is True
        assert config.cleanup_days == 30


class TestConfig:
    """Tests for main Config class"""

    def test_default_config(self):
        """Test creating default configuration"""
        config = Config()

        assert config.dab.ensemble_label == "RadioLM"
        assert config.encoder.codec == "he-aacv2"
        assert config.log_level == "INFO"

    def test_save_and_load(self):
        """Test saving and loading configuration"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "test_config.yaml")
            data_dir = os.path.join(tmpdir, "data")
            podcasts_dir = os.path.join(tmpdir, "podcasts")

            # Create and save config
            config = Config()
            config.data_dir = data_dir
            config.podcast.download_dir = podcasts_dir
            config.dab.ensemble_label = "TestRadio"
            config.save(config_path)

            # Load config
            loaded = Config.load(config_path)

            assert loaded.dab.ensemble_label == "TestRadio"
            assert os.path.exists(data_dir)

    def test_create_default_config(self):
        """Test creating default config file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            os.chdir(tmpdir)

            config = Config.create_default_config(config_path)

            assert os.path.exists(config_path)
            assert config.dab.ensemble_label == "RadioLM"
