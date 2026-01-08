#!/bin/bash
#
# Script d'installation des outils Open Digital Radio (ODR)
# pour RadioLM - DAB+ Podcast Streamer
#
# Usage: ./install_odr.sh [--with-limesdr] [--with-hackrf]
#

set -e

echo "=============================================="
echo "  Installation Open Digital Radio (ODR)"
echo "  pour RadioLM - DAB+ Podcast Streamer"
echo "=============================================="
echo ""

# Options
WITH_LIMESDR=0
WITH_HACKRF=0

for arg in "$@"; do
    case $arg in
        --with-limesdr)
            WITH_LIMESDR=1
            shift
            ;;
        --with-hackrf)
            WITH_HACKRF=1
            shift
            ;;
    esac
done

# Verifier qu'on est root ou sudo
if [ "$EUID" -ne 0 ]; then
    echo "Ce script doit etre execute avec sudo"
    echo "Usage: sudo ./install_odr.sh"
    exit 1
fi

# Repertoire de travail
WORK_DIR="/tmp/odr_install"
mkdir -p $WORK_DIR
cd $WORK_DIR

echo "[1/6] Installation des dependances systeme..."
apt-get update
apt-get install -y \
    build-essential \
    automake \
    libtool \
    pkg-config \
    git \
    libzmq3-dev \
    libzmq5 \
    libfdk-aac-dev \
    libcurl4-openssl-dev \
    libmagickwand-dev \
    libvlc-dev \
    libsamplerate0-dev \
    libasound2-dev \
    libboost-all-dev \
    libsoapysdr-dev \
    soapysdr-tools

# LimeSDR
if [ $WITH_LIMESDR -eq 1 ]; then
    echo "[1b] Installation des pilotes LimeSDR..."
    add-apt-repository -y ppa:myriadrf/drivers
    apt-get update
    apt-get install -y limesuite liblimesuite-dev soapysdr-module-lms7
fi

# HackRF
if [ $WITH_HACKRF -eq 1 ]; then
    echo "[1c] Installation des pilotes HackRF..."
    apt-get install -y libuhd-dev uhd-host hackrf libhackrf-dev
fi

echo ""
echo "[2/6] Compilation de ODR-DabMux..."
if [ -d "ODR-DabMux" ]; then
    rm -rf ODR-DabMux
fi
git clone https://github.com/Opendigitalradio/ODR-DabMux.git
cd ODR-DabMux
./bootstrap
./configure
make -j$(nproc)
make install
ldconfig
cd ..

echo ""
echo "[3/6] Compilation de ODR-DabMod..."
if [ -d "ODR-DabMod" ]; then
    rm -rf ODR-DabMod
fi
git clone https://github.com/Opendigitalradio/ODR-DabMod.git
cd ODR-DabMod
./bootstrap

# Options de configuration selon les SDR
MOD_OPTS=""
if [ $WITH_LIMESDR -eq 1 ]; then
    MOD_OPTS="$MOD_OPTS --enable-limesdr"
fi

./configure $MOD_OPTS
make -j$(nproc)
make install
ldconfig
cd ..

echo ""
echo "[4/6] Compilation de ODR-AudioEnc..."
if [ -d "ODR-AudioEnc" ]; then
    rm -rf ODR-AudioEnc
fi
git clone https://github.com/Opendigitalradio/ODR-AudioEnc.git
cd ODR-AudioEnc
./bootstrap
./configure
make -j$(nproc)
make install
ldconfig
cd ..

echo ""
echo "[5/6] Compilation de ODR-PadEnc..."
if [ -d "ODR-PadEnc" ]; then
    rm -rf ODR-PadEnc
fi
git clone https://github.com/Opendigitalradio/ODR-PadEnc.git
cd ODR-PadEnc
./bootstrap
./configure
make -j$(nproc)
make install
ldconfig
cd ..

echo ""
echo "[6/6] Verification de l'installation..."
echo ""

echo -n "odr-dabmux: "
if command -v odr-dabmux &> /dev/null; then
    echo "OK"
else
    echo "ERREUR"
fi

echo -n "odr-dabmod: "
if command -v odr-dabmod &> /dev/null; then
    echo "OK"
else
    echo "ERREUR"
fi

echo -n "odr-audioenc: "
if command -v odr-audioenc &> /dev/null; then
    echo "OK"
else
    echo "ERREUR"
fi

echo -n "odr-padenc: "
if command -v odr-padenc &> /dev/null; then
    echo "OK"
else
    echo "ERREUR"
fi

echo ""
echo "=============================================="
echo "  Installation terminee!"
echo "=============================================="
echo ""
echo "Vous pouvez maintenant utiliser RadioLM avec"
echo "la diffusion DAB+ reelle:"
echo ""
echo "  dab-streamer odr start --channel 12C audio.mp3"
echo ""
echo "ATTENTION: Respectez la reglementation radio!"
echo "En France, une autorisation CSA/ARCEP est requise"
echo "pour diffuser sur les ondes."
echo ""

# Nettoyage optionnel
read -p "Supprimer les fichiers de compilation? (o/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Oo]$ ]]; then
    rm -rf $WORK_DIR
    echo "Fichiers de compilation supprimes."
fi
