#!/usr/bin/env python3
"""
DAB+ Podcast Streamer - Interface en ligne de commande
"""

import os
import sys
import logging
import asyncio
from pathlib import Path
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from . import __version__
from .core.config import Config
from .core.podcast_manager import PodcastManager
from .core.audio_encoder import AudioEncoder
from .core.dab_multiplexer import DABMultiplexer
from .core.scheduler import BroadcastScheduler, ScheduledProgram, RepeatMode

console = Console()

# Configuration du logging
def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Fichier de configuration")
@click.option("--verbose", "-v", is_flag=True, help="Mode verbeux")
@click.version_option(version=__version__)
@click.pass_context
def main(ctx, config: str, verbose: bool):
    """
    DAB+ Podcast Streamer - Diffusion de podcasts en DAB+

    Logiciel de gestion et diffusion de podcasts sur le réseau DAB+.
    """
    ctx.ensure_object(dict)

    # Charger la configuration
    cfg = Config.load(config)
    ctx.obj["config"] = cfg
    ctx.obj["config_path"] = config

    # Setup logging
    log_level = "DEBUG" if verbose else cfg.log_level
    setup_logging(log_level)


# ============================================================================
# Commandes de configuration
# ============================================================================

@main.command("init")
@click.option("--force", "-f", is_flag=True, help="Écraser la configuration existante")
@click.pass_context
def init_config(ctx, force: bool):
    """Initialise la configuration par défaut."""
    config_path = ctx.obj["config_path"]

    if os.path.exists(config_path) and not force:
        console.print(f"[yellow]Le fichier {config_path} existe déjà.[/yellow]")
        console.print("Utilisez --force pour écraser.")
        return

    config = Config.create_default_config(config_path)
    console.print(f"[green]Configuration créée: {config_path}[/green]")

    # Afficher un résumé
    table = Table(title="Configuration DAB+")
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur", style="green")

    table.add_row("Ensemble", config.dab.ensemble_label)
    table.add_row("ID Ensemble", config.dab.ensemble_id)
    table.add_row("Bitrate", f"{config.dab.bitrate} kbps")
    table.add_row("Format sortie", config.dab.output_format)
    table.add_row("Répertoire podcasts", config.podcast.download_dir)
    table.add_row("Port web", str(config.web.port))

    console.print(table)


@main.command("config")
@click.pass_context
def show_config(ctx):
    """Affiche la configuration actuelle."""
    config: Config = ctx.obj["config"]

    console.print(Panel.fit("[bold]Configuration DAB+ Podcast Streamer[/bold]"))

    # DAB+
    table = Table(title="Configuration DAB+")
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur", style="green")

    table.add_row("Label ensemble", config.dab.ensemble_label)
    table.add_row("ID ensemble", config.dab.ensemble_id)
    table.add_row("ECC", config.dab.ensemble_ecc)
    table.add_row("ID service", config.dab.service_id)
    table.add_row("Label service", config.dab.service_label)
    table.add_row("Bitrate", f"{config.dab.bitrate} kbps")
    table.add_row("Sample rate", f"{config.dab.sample_rate} Hz")
    table.add_row("Format sortie", config.dab.output_format)

    console.print(table)

    # Encodeur
    table2 = Table(title="Configuration Encodeur")
    table2.add_column("Paramètre", style="cyan")
    table2.add_column("Valeur", style="green")

    table2.add_row("Codec", config.encoder.codec)
    table2.add_row("Bitrate", f"{config.encoder.bitrate} kbps")
    table2.add_row("FFmpeg", config.encoder.ffmpeg_path)

    console.print(table2)


@main.command("check")
@click.pass_context
def check_system(ctx):
    """Vérifie la disponibilité des outils système."""
    config: Config = ctx.obj["config"]

    console.print(Panel.fit("[bold]Vérification du système[/bold]"))

    encoder = AudioEncoder(config)
    tools = encoder.check_tools()

    table = Table(title="Outils disponibles")
    table.add_column("Outil", style="cyan")
    table.add_column("Status", style="green")

    for tool, available in tools.items():
        status = "[green]OK[/green]" if available else "[red]Non trouvé[/red]"
        table.add_row(tool, status)

    # ODR-DabMux
    mux = DABMultiplexer(config)
    mux_status = "[green]OK[/green]" if mux.odr_dabmux_available else "[red]Non trouvé[/red]"
    table.add_row("odr-dabmux", mux_status)

    console.print(table)

    # Recommandations
    if not tools.get("ffmpeg"):
        console.print("\n[yellow]FFmpeg est requis pour l'encodage audio.[/yellow]")
        console.print("Installation: sudo apt install ffmpeg")

    if not tools.get("libfdk_aac"):
        console.print("\n[yellow]libfdk_aac n'est pas disponible.[/yellow]")
        console.print("HE-AACv2 optimal nécessite FFmpeg compilé avec libfdk_aac.")

    if not mux.odr_dabmux_available:
        console.print("\n[yellow]ODR-DabMux est recommandé pour la diffusion DAB+.[/yellow]")
        console.print("https://www.opendigitalradio.org/")


# ============================================================================
# Commandes de gestion des podcasts
# ============================================================================

@main.group("podcast")
def podcast_group():
    """Gestion des podcasts."""
    pass


@podcast_group.command("add")
@click.argument("feed_url")
@click.pass_context
def podcast_add(ctx, feed_url: str):
    """Ajoute un podcast depuis son flux RSS."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Téléchargement du flux RSS...", total=None)

        try:
            podcast = manager.add_podcast(feed_url)
            console.print(f"\n[green]Podcast ajouté: {podcast.title}[/green]")
            console.print(f"  ID: {podcast.id}")
            console.print(f"  Auteur: {podcast.author}")
            console.print(f"  Épisodes: {len(podcast.episodes)}")
        except ValueError as e:
            console.print(f"[red]Erreur: {e}[/red]")


@podcast_group.command("list")
@click.pass_context
def podcast_list(ctx):
    """Liste tous les podcasts."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    podcasts = manager.get_all_podcasts()

    if not podcasts:
        console.print("[yellow]Aucun podcast enregistré.[/yellow]")
        return

    table = Table(title="Podcasts")
    table.add_column("ID", style="dim")
    table.add_column("Titre", style="cyan")
    table.add_column("Épisodes", justify="right")
    table.add_column("Téléchargés", justify="right", style="green")

    for podcast in podcasts:
        downloaded = sum(1 for ep in podcast.episodes if ep.downloaded)
        table.add_row(
            podcast.id[:8],
            podcast.title[:40],
            str(len(podcast.episodes)),
            str(downloaded),
        )

    console.print(table)


@podcast_group.command("show")
@click.argument("podcast_id")
@click.pass_context
def podcast_show(ctx, podcast_id: str):
    """Affiche les détails d'un podcast."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    # Rechercher le podcast
    podcast = None
    for p in manager.get_all_podcasts():
        if p.id.startswith(podcast_id):
            podcast = p
            break

    if not podcast:
        console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
        return

    console.print(Panel.fit(f"[bold]{podcast.title}[/bold]"))
    console.print(f"ID: {podcast.id}")
    console.print(f"Auteur: {podcast.author}")
    console.print(f"URL: {podcast.feed_url}")
    console.print(f"Langue: {podcast.language}")
    console.print()

    table = Table(title="Épisodes")
    table.add_column("ID", style="dim")
    table.add_column("Titre", style="cyan")
    table.add_column("Durée", justify="right")
    table.add_column("Status")

    for episode in podcast.episodes[:20]:
        duration = f"{episode.duration // 60}:{episode.duration % 60:02d}"
        status = "[green]Téléchargé[/green]" if episode.downloaded else "[yellow]En attente[/yellow]"
        table.add_row(
            episode.id[:8],
            episode.title[:50],
            duration,
            status,
        )

    console.print(table)


@podcast_group.command("download")
@click.argument("podcast_id")
@click.option("--episode", "-e", help="ID de l'épisode (sinon tous)")
@click.pass_context
def podcast_download(ctx, podcast_id: str, episode: str):
    """Télécharge les épisodes d'un podcast."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    # Trouver le podcast
    podcast = None
    for p in manager.get_all_podcasts():
        if p.id.startswith(podcast_id):
            podcast = p
            break

    if not podcast:
        console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        if episode:
            # Télécharger un épisode spécifique
            ep = next((e for e in podcast.episodes if e.id.startswith(episode)), None)
            if not ep:
                console.print(f"[red]Épisode non trouvé: {episode}[/red]")
                return

            task = progress.add_task(f"Téléchargement: {ep.title[:40]}...", total=None)
            path = manager.download_episode_sync(podcast.id, ep.id)

            if path:
                console.print(f"\n[green]Téléchargé: {path}[/green]")
            else:
                console.print(f"\n[red]Échec du téléchargement[/red]")
        else:
            # Télécharger tous les épisodes
            task = progress.add_task("Téléchargement des épisodes...", total=None)
            downloaded = asyncio.run(manager.download_all_episodes(podcast.id))
            console.print(f"\n[green]{len(downloaded)} épisodes téléchargés[/green]")


@podcast_group.command("refresh")
@click.argument("podcast_id", required=False)
@click.pass_context
def podcast_refresh(ctx, podcast_id: str):
    """Rafraîchit les flux RSS des podcasts."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        if podcast_id:
            # Rafraîchir un seul podcast
            podcast = None
            for p in manager.get_all_podcasts():
                if p.id.startswith(podcast_id):
                    podcast = p
                    break

            if not podcast:
                console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
                return

            progress.add_task(f"Rafraîchissement: {podcast.title}...", total=None)
            manager.refresh_podcast(podcast.id)
            console.print(f"\n[green]Podcast rafraîchi[/green]")
        else:
            # Rafraîchir tous les podcasts
            progress.add_task("Rafraîchissement de tous les podcasts...", total=None)
            results = manager.refresh_all()

            console.print("\n[green]Rafraîchissement terminé:[/green]")
            for title, new_count in results.items():
                console.print(f"  {title}: {new_count} nouveaux épisodes")


@podcast_group.command("remove")
@click.argument("podcast_id")
@click.option("--force", "-f", is_flag=True, help="Ne pas demander de confirmation")
@click.pass_context
def podcast_remove(ctx, podcast_id: str, force: bool):
    """Supprime un podcast."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)

    # Trouver le podcast
    podcast = None
    for p in manager.get_all_podcasts():
        if p.id.startswith(podcast_id):
            podcast = p
            break

    if not podcast:
        console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
        return

    if not force:
        if not click.confirm(f"Supprimer '{podcast.title}' et tous ses fichiers?"):
            return

    manager.remove_podcast(podcast.id)
    console.print(f"[green]Podcast supprimé: {podcast.title}[/green]")


# ============================================================================
# Commandes d'encodage
# ============================================================================

@main.group("encode")
def encode_group():
    """Encodage audio pour DAB+."""
    pass


@encode_group.command("file")
@click.argument("input_file")
@click.option("--output", "-o", help="Fichier de sortie")
@click.option("--bitrate", "-b", type=int, help="Bitrate en kbps")
@click.option("--codec", "-c", type=click.Choice(["aac-lc", "he-aacv1", "he-aacv2"]))
@click.pass_context
def encode_file(ctx, input_file: str, output: str, bitrate: int, codec: str):
    """Encode un fichier audio pour DAB+."""
    config: Config = ctx.obj["config"]
    encoder = AudioEncoder(config)

    if not os.path.exists(input_file):
        console.print(f"[red]Fichier non trouvé: {input_file}[/red]")
        return

    codec_enum = None
    if codec:
        from .core.audio_encoder import AudioCodec
        codec_map = {
            "aac-lc": AudioCodec.AAC_LC,
            "he-aacv1": AudioCodec.HE_AAC_V1,
            "he-aacv2": AudioCodec.HE_AAC_V2,
        }
        codec_enum = codec_map.get(codec)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Encodage en cours...", total=None)

        result = encoder.encode_file(
            input_file,
            output_path=output,
            codec=codec_enum,
            bitrate=bitrate,
        )

    if result.success:
        console.print(f"\n[green]Encodage réussi![/green]")
        console.print(f"  Fichier: {result.output_path}")
        console.print(f"  Codec: {result.codec}")
        console.print(f"  Bitrate: {result.bitrate} kbps")
        console.print(f"  Durée: {result.duration:.1f}s")
    else:
        console.print(f"\n[red]Échec de l'encodage: {result.error_message}[/red]")


@encode_group.command("podcast")
@click.argument("podcast_id")
@click.option("--all", "-a", "encode_all", is_flag=True, help="Encoder tous les épisodes téléchargés")
@click.pass_context
def encode_podcast(ctx, podcast_id: str, encode_all: bool):
    """Encode les épisodes d'un podcast pour DAB+."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)
    encoder = AudioEncoder(config)

    # Trouver le podcast
    podcast = None
    for p in manager.get_all_podcasts():
        if p.id.startswith(podcast_id):
            podcast = p
            break

    if not podcast:
        console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
        return

    episodes_to_encode = [
        ep for ep in podcast.episodes
        if ep.downloaded and ep.local_path and (encode_all or not ep.encoded_path)
    ]

    if not episodes_to_encode:
        console.print("[yellow]Aucun épisode à encoder.[/yellow]")
        return

    console.print(f"Encodage de {len(episodes_to_encode)} épisodes...")

    for episode in episodes_to_encode:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(f"Encodage: {episode.title[:40]}...", total=None)

            result = encoder.encode_file(episode.local_path)

            if result.success:
                episode.encoded_path = result.output_path
                console.print(f"  [green]OK[/green] {episode.title[:50]}")
            else:
                console.print(f"  [red]ERREUR[/red] {episode.title[:50]}")

    manager._save_db()
    console.print("\n[green]Encodage terminé[/green]")


# ============================================================================
# Commandes de diffusion
# ============================================================================

@main.group("broadcast")
def broadcast_group():
    """Gestion de la diffusion DAB+."""
    pass


@broadcast_group.command("generate-config")
@click.option("--output", "-o", default="dabmux.mux", help="Fichier de sortie")
@click.pass_context
def broadcast_generate_config(ctx, output: str):
    """Génère la configuration du multiplexeur."""
    config: Config = ctx.obj["config"]
    mux = DABMultiplexer(config)

    # Créer un service par défaut
    mux.create_default_service(config.dab.service_label)

    # Générer la configuration
    config_path = mux.generate_mux_config(output)
    console.print(f"[green]Configuration générée: {config_path}[/green]")


@broadcast_group.command("start")
@click.option("--config-file", "-c", help="Fichier de configuration du multiplexeur")
@click.pass_context
def broadcast_start(ctx, config_file: str):
    """Démarre la diffusion DAB+."""
    config: Config = ctx.obj["config"]

    # Initialiser les composants
    manager = PodcastManager(config)
    encoder = AudioEncoder(config)
    mux = DABMultiplexer(config)
    scheduler = BroadcastScheduler(config, manager, encoder, mux)

    if not mux.odr_dabmux_available:
        console.print("[yellow]ODR-DabMux n'est pas disponible.[/yellow]")
        console.print("La diffusion fonctionnera en mode simulation.")

    # Créer le service
    service_id = mux.create_default_service()

    # Configurer le FIFO
    fifo_path = mux.create_fifo("audio_input.fifo")
    mux.subchannels[config.dab.subchannel_id].input_file = fifo_path
    mux.subchannels[config.dab.subchannel_id].input_type = "fifo"

    console.print(Panel.fit("[bold]Démarrage de la diffusion DAB+[/bold]"))
    console.print(f"Service: {config.dab.service_label}")
    console.print(f"ID: {service_id}")

    # Démarrer le multiplexeur
    if mux.odr_dabmux_available:
        mux_config = config_file or mux.generate_mux_config()
        mux.start_multiplexer(mux_config)
        console.print("[green]Multiplexeur démarré[/green]")

    # Démarrer le scheduler
    scheduler.start(service_id)
    console.print("[green]Scheduler démarré[/green]")

    # Remplir la playlist si vide
    if not scheduler.playlist:
        added = scheduler.auto_fill_playlist()
        console.print(f"[cyan]Playlist remplie avec {added} épisodes[/cyan]")

    console.print("\n[bold]Diffusion en cours...[/bold]")
    console.print("Appuyez sur Ctrl+C pour arrêter.\n")

    try:
        while True:
            status = scheduler.get_status()
            if status["current_item"]:
                rprint(f"[cyan]En cours: {status['current_item']['episode']}[/cyan]", end="\r")
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Arrêt de la diffusion...[/yellow]")
        scheduler.shutdown()
        mux.stop_multiplexer()
        console.print("[green]Diffusion arrêtée[/green]")


@broadcast_group.command("status")
@click.pass_context
def broadcast_status(ctx):
    """Affiche l'état de la diffusion."""
    config: Config = ctx.obj["config"]
    mux = DABMultiplexer(config)

    status = mux.get_status()

    table = Table(title="État de la diffusion")
    table.add_column("Paramètre", style="cyan")
    table.add_column("Valeur")

    table.add_row("En cours", "[green]Oui[/green]" if status["running"] else "[red]Non[/red]")
    table.add_row("ODR-DabMux", "[green]Disponible[/green]" if status["odr_dabmux_available"] else "[yellow]Non disponible[/yellow]")
    table.add_row("Ensemble", status["ensemble"]["label"])
    table.add_row("Services", str(status["services"]))
    table.add_row("Sous-canaux", str(status["subchannels"]))

    console.print(table)


# ============================================================================
# Commandes de programmation
# ============================================================================

@main.group("schedule")
def schedule_group():
    """Programmation de la diffusion."""
    pass


@schedule_group.command("add")
@click.argument("name")
@click.argument("podcast_id")
@click.option("--time", "-t", default="08:00", help="Heure de diffusion (HH:MM)")
@click.option("--repeat", "-r", type=click.Choice(["once", "daily", "weekly", "weekdays", "weekend"]), default="daily")
@click.pass_context
def schedule_add(ctx, name: str, podcast_id: str, time: str, repeat: str):
    """Ajoute un programme planifié."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)
    encoder = AudioEncoder(config)
    mux = DABMultiplexer(config)
    scheduler = BroadcastScheduler(config, manager, encoder, mux)

    # Vérifier le podcast
    podcast = None
    for p in manager.get_all_podcasts():
        if p.id.startswith(podcast_id):
            podcast = p
            break

    if not podcast:
        console.print(f"[red]Podcast non trouvé: {podcast_id}[/red]")
        return

    import hashlib
    program_id = hashlib.sha256(f"{name}{time}".encode()).hexdigest()[:8]

    program = ScheduledProgram(
        id=program_id,
        name=name,
        podcast_id=podcast.id,
        start_time=time,
        repeat_mode=RepeatMode(repeat),
    )

    scheduler.add_program(program)
    console.print(f"[green]Programme ajouté: {name} à {time} ({repeat})[/green]")


@schedule_group.command("list")
@click.pass_context
def schedule_list(ctx):
    """Liste les programmes planifiés."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)
    encoder = AudioEncoder(config)
    mux = DABMultiplexer(config)
    scheduler = BroadcastScheduler(config, manager, encoder, mux)

    programs = scheduler.get_all_programs()

    if not programs:
        console.print("[yellow]Aucun programme planifié.[/yellow]")
        return

    table = Table(title="Programmes planifiés")
    table.add_column("ID", style="dim")
    table.add_column("Nom", style="cyan")
    table.add_column("Heure")
    table.add_column("Répétition")
    table.add_column("Status")

    for prog in programs:
        status = "[green]Actif[/green]" if prog.enabled else "[red]Inactif[/red]"
        table.add_row(
            prog.id[:8],
            prog.name,
            prog.start_time,
            prog.repeat_mode.value,
            status,
        )

    console.print(table)


@schedule_group.command("remove")
@click.argument("program_id")
@click.pass_context
def schedule_remove(ctx, program_id: str):
    """Supprime un programme planifié."""
    config: Config = ctx.obj["config"]
    manager = PodcastManager(config)
    encoder = AudioEncoder(config)
    mux = DABMultiplexer(config)
    scheduler = BroadcastScheduler(config, manager, encoder, mux)

    # Trouver le programme
    program = None
    for p in scheduler.get_all_programs():
        if p.id.startswith(program_id):
            program = p
            break

    if not program:
        console.print(f"[red]Programme non trouvé: {program_id}[/red]")
        return

    scheduler.remove_program(program.id)
    console.print(f"[green]Programme supprimé: {program.name}[/green]")


# ============================================================================
# Commande serveur web
# ============================================================================

@main.command("web")
@click.option("--host", "-h", help="Adresse d'écoute")
@click.option("--port", "-p", type=int, help="Port d'écoute")
@click.pass_context
def run_web(ctx, host: str, port: int):
    """Démarre l'interface web."""
    config: Config = ctx.obj["config"]

    host = host or config.web.host
    port = port or config.web.port

    console.print(f"[green]Démarrage du serveur web sur http://{host}:{port}[/green]")

    from .web.app import create_app
    app = create_app(config)
    app.run(host=host, port=port, debug=config.web.debug)


# ============================================================================
# Commandes ODR - Diffusion DAB+ reelle
# ============================================================================

@main.group("odr")
def odr_group():
    """Diffusion DAB+ reelle avec Open Digital Radio."""
    pass


@odr_group.command("check")
@click.pass_context
def odr_check(ctx):
    """Verifie l'installation des outils ODR."""
    config: Config = ctx.obj["config"]

    from .core.odr_broadcast import ODRBroadcast, ODRInstaller

    console.print(Panel.fit("[bold]Verification des outils ODR[/bold]"))

    odr = ODRBroadcast(config)
    tools = odr.odr_tools_available

    table = Table(title="Outils Open Digital Radio")
    table.add_column("Outil", style="cyan")
    table.add_column("Status")
    table.add_column("Description")

    descriptions = {
        "odr-dabmux": "Multiplexeur DAB+",
        "odr-dabmod": "Modulateur OFDM",
        "odr-audioenc": "Encodeur audio DAB+",
        "odr-padenc": "Encodeur PAD (DLS/Slideshow)",
    }

    all_ok = True
    for tool, available in tools.items():
        status = "[green]OK[/green]" if available else "[red]Non installe[/red]"
        if not available:
            all_ok = False
        table.add_row(tool, status, descriptions.get(tool, ""))

    console.print(table)

    if not all_ok:
        console.print("\n[yellow]Certains outils ODR ne sont pas installes.[/yellow]")
        console.print("Pour installer, executez:")
        console.print("  [cyan]sudo ./scripts/install_odr.sh[/cyan]")
        console.print("\nOu consultez: https://www.opendigitalradio.org/")

    # Verifier les dependances
    console.print("\n[bold]Dependances systeme:[/bold]")
    deps = ODRInstaller.check_dependencies()
    for dep, available in deps.items():
        status = "[green]OK[/green]" if available else "[yellow]Manquant[/yellow]"
        console.print(f"  {dep}: {status}")


@odr_group.command("channels")
def odr_channels():
    """Liste les canaux DAB+ disponibles en France."""
    from .core.odr_broadcast import ODRBroadcast

    console.print(Panel.fit("[bold]Canaux DAB+ France (Bande III)[/bold]"))

    channels = ODRBroadcast.get_available_channels()

    table = Table(title="Canaux disponibles")
    table.add_column("Canal", style="cyan")
    table.add_column("Frequence (MHz)", justify="right")

    for channel, freq in sorted(channels.items(), key=lambda x: x[1]):
        table.add_row(channel, f"{freq:.3f}")

    console.print(table)

    console.print("\n[yellow]ATTENTION: La diffusion radio est reglementee![/yellow]")
    console.print("En France, une autorisation CSA/ARCEP est requise.")


@odr_group.command("start")
@click.argument("audio_source")
@click.option("--channel", "-c", default="12C", help="Canal DAB+ (ex: 12C)")
@click.option("--power", "-p", type=float, default=-10.0, help="Puissance en dBm")
@click.option("--device", "-d", default="driver=lime", help="Device SDR")
@click.pass_context
def odr_start(ctx, audio_source: str, channel: str, power: float, device: str):
    """
    Demarre la diffusion DAB+ reelle.

    AUDIO_SOURCE peut etre:
    - Un fichier audio (mp3, wav, etc.)
    - alsa:default (entree audio ALSA)
    - jack (entree JACK)

    ATTENTION: Respectez la reglementation radio!
    """
    config: Config = ctx.obj["config"]

    from .core.odr_broadcast import ODRBroadcast, ODRConfig, OutputType

    console.print(Panel.fit("[bold red]DIFFUSION DAB+ REELLE[/bold red]"))
    console.print("")
    console.print("[yellow]ATTENTION: La diffusion radio est reglementee![/yellow]")
    console.print("[yellow]Assurez-vous d'avoir les autorisations necessaires.[/yellow]")
    console.print("")

    if not click.confirm("Voulez-vous continuer?"):
        return

    odr = ODRBroadcast(config)

    # Verifier les outils
    if not all(odr.odr_tools_available.values()):
        console.print("[red]Certains outils ODR ne sont pas installes.[/red]")
        console.print("Executez: dab-streamer odr check")
        return

    # Configurer
    odr_config = ODRConfig(
        output_power_dbm=power,
        sdr_device=device,
        output_type=OutputType.SOAPYSDR,
    )
    odr.configure(odr_config)

    # Definir le canal
    if not odr.set_channel(channel):
        console.print(f"[red]Canal invalide: {channel}[/red]")
        console.print("Utilisez: dab-streamer odr channels")
        return

    console.print(f"\n[bold]Configuration:[/bold]")
    console.print(f"  Radio: {config.dab.ensemble_label}")
    console.print(f"  Canal: {channel} ({odr.odr_config.frequency_mhz} MHz)")
    console.print(f"  Puissance: {power} dBm")
    console.print(f"  Source: {audio_source}")
    console.print("")

    # Demarrer la diffusion
    console.print("[cyan]Demarrage de la diffusion...[/cyan]")

    if not odr.start_broadcast(audio_source):
        console.print("[red]Echec du demarrage de la diffusion[/red]")
        return

    console.print("\n[green]Diffusion DAB+ en cours![/green]")
    console.print("Appuyez sur Ctrl+C pour arreter.\n")

    try:
        while True:
            status = odr.get_status()
            uptime = status["uptime_formatted"]
            rprint(f"[cyan]RadioLM | Canal {channel} | Uptime: {uptime}[/cyan]", end="\r")
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Arret de la diffusion...[/yellow]")
        odr.stop_broadcast()
        console.print("[green]Diffusion arretee[/green]")


@odr_group.command("stop")
@click.pass_context
def odr_stop(ctx):
    """Arrete la diffusion DAB+ reelle."""
    console.print("[yellow]Arret de tous les processus ODR...[/yellow]")

    import subprocess
    for proc in ["odr-audioenc", "odr-padenc", "odr-dabmod", "odr-dabmux"]:
        try:
            subprocess.run(["pkill", "-f", proc], capture_output=True)
        except Exception:
            pass

    console.print("[green]Processus ODR arretes[/green]")


@odr_group.command("status")
@click.pass_context
def odr_status(ctx):
    """Affiche l'etat de la diffusion ODR."""
    config: Config = ctx.obj["config"]

    from .core.odr_broadcast import ODRBroadcast

    odr = ODRBroadcast(config)
    status = odr.get_status()

    table = Table(title="Etat diffusion ODR")
    table.add_column("Composant", style="cyan")
    table.add_column("Status")

    table.add_row("Diffusion active", "[green]Oui[/green]" if status["is_running"] else "[red]Non[/red]")
    table.add_row("Multiplexeur", "[green]OK[/green]" if status["mux_running"] else "[dim]Arrete[/dim]")
    table.add_row("Modulateur", "[green]OK[/green]" if status["mod_running"] else "[dim]Arrete[/dim]")
    table.add_row("Encodeur", "[green]OK[/green]" if status["encoder_running"] else "[dim]Arrete[/dim]")

    if status["frequency_mhz"] > 0:
        table.add_row("Frequence", f"{status['frequency_mhz']} MHz")
        table.add_row("Puissance", f"{status['output_power_dbm']} dBm")
        table.add_row("Uptime", status["uptime_formatted"])

    if status["last_error"]:
        table.add_row("Derniere erreur", f"[red]{status['last_error']}[/red]")

    console.print(table)


@odr_group.command("dls")
@click.argument("text")
@click.pass_context
def odr_dls(ctx, text: str):
    """Met a jour le Dynamic Label (texte defilant)."""
    config: Config = ctx.obj["config"]

    from .core.odr_broadcast import ODRBroadcast

    odr = ODRBroadcast(config)
    if odr.update_dls(text):
        console.print(f"[green]DLS mis a jour: {text}[/green]")
    else:
        console.print("[red]Erreur lors de la mise a jour du DLS[/red]")


@odr_group.command("install")
def odr_install():
    """Affiche les instructions d'installation ODR."""
    from .core.odr_broadcast import ODRInstaller

    console.print(Panel.fit("[bold]Installation Open Digital Radio[/bold]"))
    console.print(ODRInstaller.get_install_instructions())


if __name__ == "__main__":
    main()
