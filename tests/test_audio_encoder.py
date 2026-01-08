"""
Tests for audio encoder module
"""

import os
import tempfile
import pytest
from dab_streamer.core.config import Config
from dab_streamer.core.audio_encoder import AudioEncoder, AudioCodec, EncodingResult


class TestAudioCodec:
    """Tests for AudioCodec enum"""

    def test_codec_values(self):
        """Test codec enum values"""
        assert AudioCodec.AAC_LC.value == "aac-lc"
        assert AudioCodec.HE_AAC_V1.value == "he-aacv1"
        assert AudioCodec.HE_AAC_V2.value == "he-aacv2"


class TestEncodingResult:
    """Tests for EncodingResult dataclass"""

    def test_successful_result(self):
        """Test successful encoding result"""
        result = EncodingResult(
            success=True,
            input_path="/input/file.mp3",
            output_path="/output/file.aac",
            codec="he-aacv2",
            bitrate=64,
            duration=3600.0,
        )

        assert result.success is True
        assert result.error_message == ""

    def test_failed_result(self):
        """Test failed encoding result"""
        result = EncodingResult(
            success=False,
            input_path="/input/file.mp3",
            output_path="/output/file.aac",
            codec="he-aacv2",
            bitrate=64,
            duration=0,
            error_message="Encoding failed",
        )

        assert result.success is False
        assert result.error_message == "Encoding failed"


class TestAudioEncoder:
    """Tests for AudioEncoder class"""

    def test_encoder_creation(self):
        """Test creating audio encoder"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.data_dir = os.path.join(tmpdir, "data")
            config.podcast.download_dir = os.path.join(tmpdir, "podcasts")

            encoder = AudioEncoder(config)

            assert encoder.config == config
            assert os.path.exists(encoder.output_dir)

    def test_get_codec(self):
        """Test getting codec from config"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.data_dir = os.path.join(tmpdir, "data")
            config.podcast.download_dir = os.path.join(tmpdir, "podcasts")
            config.encoder.codec = "he-aacv2"

            encoder = AudioEncoder(config)
            codec = encoder.get_codec()

            assert codec == AudioCodec.HE_AAC_V2

    def test_recommended_bitrates(self):
        """Test recommended bitrates for each codec"""
        assert 64 in AudioEncoder.RECOMMENDED_BITRATES[AudioCodec.HE_AAC_V2]
        assert 96 in AudioEncoder.RECOMMENDED_BITRATES[AudioCodec.AAC_LC]
        assert 48 in AudioEncoder.RECOMMENDED_BITRATES[AudioCodec.HE_AAC_V1]

    def test_check_tools(self):
        """Test tool availability check"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config()
            config.data_dir = os.path.join(tmpdir, "data")
            config.podcast.download_dir = os.path.join(tmpdir, "podcasts")

            encoder = AudioEncoder(config)
            tools = encoder.check_tools()

            assert "ffmpeg" in tools
            assert "odr-audioenc" in tools
            assert "libfdk_aac" in tools
