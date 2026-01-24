#!/bin/bash
# setup.sh - Configure NeoAlchemy trading bot environment
# Run once on new VM or after system updates

set -e  # Exit on any error

echo "================================================"
echo "NeoAlchemy Trading Bot - Environment Setup"
echo "================================================"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root: sudo ./setup.sh"
    exit 1
fi

echo ""
echo "${YELLOW}[1/6] Installing system dependencies...${NC}"
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    git \
    postgresql-client \
    build-essential

echo ""
echo "${GREEN}✓ System dependencies installed${NC}"

echo ""
echo "${YELLOW}[2/6] Creating Python virtual environment...${NC}"
# Remove old venv if exists
if [ -d "venv" ]; then
    echo "Removing old virtual environment..."
    rm -rf venv
fi

# Create new venv as the actual user (not root)
ACTUAL_USER=$(who am i | awk '{print $1}')
if [ -z "$ACTUAL_USER" ]; then
    ACTUAL_USER="root"
fi

sudo -u $ACTUAL_USER python3 -m venv venv
echo "${GREEN}✓ Virtual environment created${NC}"

echo ""
echo "${YELLOW}[3/6] Activating virtual environment...${NC}"
# Activate venv
source venv/bin/activate
echo "${GREEN}✓ Virtual environment activated${NC}"

echo ""
echo "${YELLOW}[4/6] Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel
echo "${GREEN}✓ pip upgraded${NC}"

echo ""
echo "${YELLOW}[5/6] Installing Python dependencies...${NC}"
pip install -r requirements.txt
echo "${GREEN}✓ Python dependencies installed${NC}"

echo ""
echo "${YELLOW}[6/6] Verifying installation...${NC}"
python -c "import pandas; print(f'  ✓ pandas {pandas.__version__}')"
python -c "import numpy; print(f'  ✓ numpy {numpy.__version__}')"
python -c "import alpaca; print('  ✓ alpaca-py installed')"
python -c "import psycopg; print(f'  ✓ psycopg {psycopg.__version__}')"

echo ""
echo "${GREEN}================================================${NC}"
echo "${GREEN}✓ Setup complete!${NC}"
echo "${GREEN}================================================${NC}"
echo ""
echo "To activate the environment in the future:"
echo "  source venv/bin/activate"
echo ""
echo "To run the trading bot:"
echo "  source venv/bin/activate"
echo "  python engines.py live"
echo ""
