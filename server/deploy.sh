#!/bin/bash
# deploy.sh - Deploy/update NeoAlchemy bot on VM
# Run this after pushing code changes to update the running bot

set -e

echo "================================================"
echo "NeoAlchemy Trading Bot - Deployment"
echo "================================================"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "${YELLOW}[1/5] Pulling latest code...${NC}"
git pull origin main
echo "${GREEN}✓ Code updated${NC}"

echo ""
echo "${YELLOW}[2/5] Activating virtual environment...${NC}"
source venv/bin/activate
echo "${GREEN}✓ Virtual environment activated${NC}"

echo ""
echo "${YELLOW}[3/5] Installing/updating dependencies...${NC}"
pip install -r requirements.txt --upgrade
echo "${GREEN}✓ Dependencies updated${NC}"

echo ""
echo "${YELLOW}[4/5] Restarting bot service...${NC}"
if systemctl is-active --quiet neoalchemy; then
    sudo systemctl restart neoalchemy
    echo "${GREEN}✓ Bot service restarted${NC}"
else
    echo "${YELLOW}Service not running, starting it...${NC}"
    sudo systemctl start neoalchemy
    echo "${GREEN}✓ Bot service started${NC}"
fi

echo ""
echo "${YELLOW}[5/5] Checking service status...${NC}"
sudo systemctl status neoalchemy --no-pager

echo ""
echo "${GREEN}================================================${NC}"
echo "${GREEN}✓ Deployment complete!${NC}"
echo "${GREEN}================================================${NC}"
echo ""
echo "View logs:"
echo "  sudo journalctl -u neoalchemy -f"
echo ""
