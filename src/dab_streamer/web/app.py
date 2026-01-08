"""
Flask Web Application for DAB+ Podcast Streamer
"""

import os
import asyncio
import logging
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS

from ..core.config import Config
from ..core.podcast_manager import PodcastManager
from ..core.audio_encoder import AudioEncoder
from ..core.dab_multiplexer import DABMultiplexer
from ..core.scheduler import BroadcastScheduler, ScheduledProgram, RepeatMode

logger = logging.getLogger(__name__)


def create_app(config: Config = None) -> Flask:
    """Create and configure the Flask application."""

    if config is None:
        config = Config.load()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = config.web.secret_key
    CORS(app)

    # Initialize components
    podcast_manager = PodcastManager(config)
    encoder = AudioEncoder(config)
    multiplexer = DABMultiplexer(config)
    scheduler = BroadcastScheduler(config, podcast_manager, encoder, multiplexer)

    # Store in app context
    app.config["dab_config"] = config
    app.config["podcast_manager"] = podcast_manager
    app.config["encoder"] = encoder
    app.config["multiplexer"] = multiplexer
    app.config["scheduler"] = scheduler

    # ========================================================================
    # Web Routes (HTML)
    # ========================================================================

    @app.route("/")
    def index():
        """Main dashboard."""
        return render_template("index.html")

    @app.route("/podcasts")
    def podcasts_page():
        """Podcasts management page."""
        return render_template("podcasts.html")

    @app.route("/broadcast")
    def broadcast_page():
        """Broadcast control page."""
        return render_template("broadcast.html")

    @app.route("/schedule")
    def schedule_page():
        """Schedule management page."""
        return render_template("schedule.html")

    @app.route("/settings")
    def settings_page():
        """Settings page."""
        return render_template("settings.html")

    # ========================================================================
    # API Routes - Podcasts
    # ========================================================================

    @app.route("/api/podcasts", methods=["GET"])
    def api_get_podcasts():
        """Get all podcasts."""
        podcasts = podcast_manager.get_all_podcasts()
        return jsonify({
            "success": True,
            "podcasts": [p.to_dict() for p in podcasts],
        })

    @app.route("/api/podcasts", methods=["POST"])
    def api_add_podcast():
        """Add a new podcast."""
        data = request.get_json()
        feed_url = data.get("feed_url")

        if not feed_url:
            return jsonify({"success": False, "error": "feed_url is required"}), 400

        try:
            podcast = podcast_manager.add_podcast(feed_url)
            return jsonify({
                "success": True,
                "podcast": podcast.to_dict(),
            })
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/api/podcasts/<podcast_id>", methods=["GET"])
    def api_get_podcast(podcast_id: str):
        """Get a specific podcast."""
        podcast = podcast_manager.get_podcast(podcast_id)

        if not podcast:
            return jsonify({"success": False, "error": "Podcast not found"}), 404

        return jsonify({
            "success": True,
            "podcast": podcast.to_dict(),
        })

    @app.route("/api/podcasts/<podcast_id>", methods=["DELETE"])
    def api_delete_podcast(podcast_id: str):
        """Delete a podcast."""
        if podcast_manager.remove_podcast(podcast_id):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Podcast not found"}), 404

    @app.route("/api/podcasts/<podcast_id>/refresh", methods=["POST"])
    def api_refresh_podcast(podcast_id: str):
        """Refresh a podcast's feed."""
        podcast = podcast_manager.refresh_podcast(podcast_id)

        if podcast:
            return jsonify({
                "success": True,
                "podcast": podcast.to_dict(),
            })
        else:
            return jsonify({"success": False, "error": "Podcast not found"}), 404

    @app.route("/api/podcasts/<podcast_id>/episodes/<episode_id>/download", methods=["POST"])
    def api_download_episode(podcast_id: str, episode_id: str):
        """Download an episode."""
        path = podcast_manager.download_episode_sync(podcast_id, episode_id)

        if path:
            return jsonify({
                "success": True,
                "path": path,
            })
        else:
            return jsonify({"success": False, "error": "Download failed"}), 500

    # ========================================================================
    # API Routes - Encoding
    # ========================================================================

    @app.route("/api/encode", methods=["POST"])
    def api_encode_file():
        """Encode a file for DAB+."""
        data = request.get_json()
        input_path = data.get("input_path")

        if not input_path:
            return jsonify({"success": False, "error": "input_path is required"}), 400

        if not os.path.exists(input_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        result = encoder.encode_file(
            input_path,
            bitrate=data.get("bitrate"),
        )

        return jsonify({
            "success": result.success,
            "output_path": result.output_path,
            "codec": result.codec,
            "bitrate": result.bitrate,
            "duration": result.duration,
            "error": result.error_message if not result.success else None,
        })

    @app.route("/api/encoder/status", methods=["GET"])
    def api_encoder_status():
        """Get encoder status."""
        tools = encoder.check_tools()
        return jsonify({
            "success": True,
            "tools": tools,
        })

    # ========================================================================
    # API Routes - Broadcast
    # ========================================================================

    @app.route("/api/broadcast/status", methods=["GET"])
    def api_broadcast_status():
        """Get broadcast status."""
        mux_status = multiplexer.get_status()
        sched_status = scheduler.get_status()

        return jsonify({
            "success": True,
            "multiplexer": mux_status,
            "scheduler": sched_status,
        })

    @app.route("/api/broadcast/start", methods=["POST"])
    def api_broadcast_start():
        """Start broadcasting."""
        # Create default service if not exists
        if not multiplexer.services:
            service_id = multiplexer.create_default_service()
        else:
            service_id = list(multiplexer.services.keys())[0]

        # Start scheduler
        scheduler.start(service_id)

        return jsonify({
            "success": True,
            "service_id": service_id,
        })

    @app.route("/api/broadcast/stop", methods=["POST"])
    def api_broadcast_stop():
        """Stop broadcasting."""
        scheduler.shutdown()
        multiplexer.stop_multiplexer()

        return jsonify({"success": True})

    @app.route("/api/broadcast/play", methods=["POST"])
    def api_broadcast_play():
        """Start playback."""
        success = scheduler.play()
        return jsonify({"success": success})

    @app.route("/api/broadcast/pause", methods=["POST"])
    def api_broadcast_pause():
        """Pause playback."""
        scheduler.pause()
        return jsonify({"success": True})

    @app.route("/api/broadcast/skip", methods=["POST"])
    def api_broadcast_skip():
        """Skip to next track."""
        success = scheduler.skip()
        return jsonify({"success": success})

    @app.route("/api/broadcast/previous", methods=["POST"])
    def api_broadcast_previous():
        """Go to previous track."""
        success = scheduler.previous()
        return jsonify({"success": success})

    # ========================================================================
    # API Routes - Playlist
    # ========================================================================

    @app.route("/api/playlist", methods=["GET"])
    def api_get_playlist():
        """Get current playlist."""
        playlist = scheduler.get_playlist()
        return jsonify({
            "success": True,
            "playlist": playlist,
        })

    @app.route("/api/playlist/add", methods=["POST"])
    def api_add_to_playlist():
        """Add an episode to playlist."""
        data = request.get_json()
        podcast_id = data.get("podcast_id")
        episode_id = data.get("episode_id")

        if not podcast_id or not episode_id:
            return jsonify({"success": False, "error": "podcast_id and episode_id required"}), 400

        podcast = podcast_manager.get_podcast(podcast_id)
        episode = podcast_manager.get_episode(podcast_id, episode_id)

        if not podcast or not episode:
            return jsonify({"success": False, "error": "Podcast or episode not found"}), 404

        scheduler.add_to_playlist(podcast, episode)
        return jsonify({"success": True})

    @app.route("/api/playlist/<int:index>", methods=["DELETE"])
    def api_remove_from_playlist(index: int):
        """Remove an item from playlist."""
        success = scheduler.remove_from_playlist(index)
        return jsonify({"success": success})

    @app.route("/api/playlist/clear", methods=["POST"])
    def api_clear_playlist():
        """Clear the playlist."""
        scheduler.clear_playlist()
        return jsonify({"success": True})

    @app.route("/api/playlist/shuffle", methods=["POST"])
    def api_shuffle_playlist():
        """Shuffle the playlist."""
        scheduler.shuffle_playlist()
        return jsonify({"success": True})

    @app.route("/api/playlist/auto-fill", methods=["POST"])
    def api_auto_fill_playlist():
        """Auto-fill the playlist."""
        data = request.get_json() or {}
        hours = data.get("hours", 4)
        added = scheduler.auto_fill_playlist(hours)
        return jsonify({
            "success": True,
            "added": added,
        })

    # ========================================================================
    # API Routes - Schedule
    # ========================================================================

    @app.route("/api/schedule", methods=["GET"])
    def api_get_schedules():
        """Get all scheduled programs."""
        programs = scheduler.get_all_programs()
        return jsonify({
            "success": True,
            "programs": [p.to_dict() for p in programs],
        })

    @app.route("/api/schedule", methods=["POST"])
    def api_add_schedule():
        """Add a scheduled program."""
        data = request.get_json()

        required = ["name", "podcast_id", "start_time"]
        for field in required:
            if field not in data:
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        import hashlib
        program_id = hashlib.sha256(
            f"{data['name']}{data['start_time']}".encode()
        ).hexdigest()[:8]

        program = ScheduledProgram(
            id=program_id,
            name=data["name"],
            podcast_id=data["podcast_id"],
            episode_id=data.get("episode_id"),
            start_time=data["start_time"],
            repeat_mode=RepeatMode(data.get("repeat_mode", "daily")),
            days=data.get("days", []),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
        )

        scheduler.add_program(program)
        return jsonify({
            "success": True,
            "program": program.to_dict(),
        })

    @app.route("/api/schedule/<program_id>", methods=["DELETE"])
    def api_delete_schedule(program_id: str):
        """Delete a scheduled program."""
        if scheduler.remove_program(program_id):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Program not found"}), 404

    @app.route("/api/schedule/<program_id>", methods=["PUT"])
    def api_update_schedule(program_id: str):
        """Update a scheduled program."""
        data = request.get_json()

        program = scheduler.get_program(program_id)
        if not program:
            return jsonify({"success": False, "error": "Program not found"}), 404

        # Update fields
        if "name" in data:
            program.name = data["name"]
        if "start_time" in data:
            program.start_time = data["start_time"]
        if "repeat_mode" in data:
            program.repeat_mode = RepeatMode(data["repeat_mode"])
        if "enabled" in data:
            program.enabled = data["enabled"]
        if "days" in data:
            program.days = data["days"]

        scheduler.update_program(program)
        return jsonify({
            "success": True,
            "program": program.to_dict(),
        })

    # ========================================================================
    # API Routes - Settings
    # ========================================================================

    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        """Get current settings."""
        cfg = app.config["dab_config"]
        return jsonify({
            "success": True,
            "settings": {
                "dab": {
                    "ensemble_label": cfg.dab.ensemble_label,
                    "ensemble_id": cfg.dab.ensemble_id,
                    "service_label": cfg.dab.service_label,
                    "bitrate": cfg.dab.bitrate,
                    "output_format": cfg.dab.output_format,
                },
                "encoder": {
                    "codec": cfg.encoder.codec,
                    "bitrate": cfg.encoder.bitrate,
                },
                "podcast": {
                    "max_episodes": cfg.podcast.max_episodes,
                    "auto_cleanup": cfg.podcast.auto_cleanup,
                    "cleanup_days": cfg.podcast.cleanup_days,
                },
            },
        })

    @app.route("/api/settings", methods=["PUT"])
    def api_update_settings():
        """Update settings."""
        data = request.get_json()
        cfg = app.config["dab_config"]

        if "dab" in data:
            for key, value in data["dab"].items():
                if hasattr(cfg.dab, key):
                    setattr(cfg.dab, key, value)

        if "encoder" in data:
            for key, value in data["encoder"].items():
                if hasattr(cfg.encoder, key):
                    setattr(cfg.encoder, key, value)

        if "podcast" in data:
            for key, value in data["podcast"].items():
                if hasattr(cfg.podcast, key):
                    setattr(cfg.podcast, key, value)

        cfg.save()
        return jsonify({"success": True})

    @app.route("/api/system/info", methods=["GET"])
    def api_system_info():
        """Get system information."""
        from .. import __version__

        return jsonify({
            "success": True,
            "version": __version__,
            "tools": encoder.check_tools(),
            "odr_dabmux": multiplexer.odr_dabmux_available,
        })

    return app


def run_server():
    """Run the web server."""
    config = Config.load()
    app = create_app(config)
    app.run(
        host=config.web.host,
        port=config.web.port,
        debug=config.web.debug,
    )


if __name__ == "__main__":
    run_server()
