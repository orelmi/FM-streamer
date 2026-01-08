#!/bin/bash
#
# Script de demarrage rapide RadioLM en mode DAB+ reel
#
# Usage: ./start_radiolm.sh [canal] [source_audio]
# Exemple: ./start_radiolm.sh 12C playlist.m3u
#

set -e

# Configuration par defaut
CHANNEL=${1:-"12C"}
AUDIO_SOURCE=${2:-"alsa:default"}
CONFIG_DIR="./odr_config"

echo "=============================================="
echo "        RadioLM - DAB+ Broadcast"
echo "=============================================="
echo ""
echo "Canal: $CHANNEL"
echo "Source audio: $AUDIO_SOURCE"
echo ""
echo "ATTENTION: Assurez-vous d'avoir l'autorisation"
echo "de diffuser sur les ondes radio!"
echo ""

# Verifier les outils
for tool in odr-dabmux odr-dabmod odr-audioenc; do
    if ! command -v $tool &> /dev/null; then
        echo "ERREUR: $tool n'est pas installe"
        echo "Executez: sudo ./scripts/install_odr.sh"
        exit 1
    fi
done

# Creer le repertoire de configuration
mkdir -p $CONFIG_DIR

# Fonction de nettoyage
cleanup() {
    echo ""
    echo "Arret de la diffusion..."
    pkill -f odr-audioenc 2>/dev/null || true
    pkill -f odr-padenc 2>/dev/null || true
    pkill -f odr-dabmod 2>/dev/null || true
    pkill -f odr-dabmux 2>/dev/null || true
    echo "Diffusion arretee."
}

trap cleanup EXIT

# Demarrer avec dab-streamer
echo "Demarrage de la diffusion DAB+..."
dab-streamer odr start --channel "$CHANNEL" "$AUDIO_SOURCE"
