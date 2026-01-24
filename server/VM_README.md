# NeoAlchemy VM Setup & Deployment

## 🚀 Initial Setup (Run Once)

On a fresh VM or after system reset:

```bash
cd /root/NeoAlchemy

# Make scripts executable
chmod +x setup.sh deploy.sh

# Run setup (installs everything)
sudo ./setup.sh
```

This will:
- ✅ Install system dependencies (python3, pip, etc.)
- ✅ Create Python virtual environment
- ✅ Install all Python packages
- ✅ Verify installation

---

## 🔄 Daily Workflow

### **Run Bot Manually (For Testing)**
```bash
cd /root/NeoAlchemy
source venv/bin/activate
python engines.py live
```

### **Run Bot as Service (For Production)**

**Install service:**
```bash
sudo cp neoalchemy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable neoalchemy
sudo systemctl start neoalchemy
```

**Manage service:**
```bash
# Check status
sudo systemctl status neoalchemy

# Stop bot
sudo systemctl stop neoalchemy

# Start bot
sudo systemctl start neoalchemy

# Restart bot
sudo systemctl restart neoalchemy

# View live logs
sudo journalctl -u neoalchemy -f

# View recent logs
sudo journalctl -u neoalchemy -n 100 --no-pager
```

---

## 📦 Deploying Updates

After pushing code changes to the repo:

```bash
cd /root/NeoAlchemy
./deploy.sh
```

This will:
- ✅ Pull latest code from git
- ✅ Update dependencies
- ✅ Restart the bot service
- ✅ Show service status

---

## 📁 Directory Structure

```
/root/NeoAlchemy/
├── venv/                   # Python virtual environment
├── logs/                   # Bot logs
│   ├── bot.log            # Standard output
│   ├── bot-error.log      # Error output
│   └── alchemy.log        # Application logs
├── secrets                # API keys (git-ignored)
├── engines.py             # Main bot entry point
├── agents.py              # Trading agents
├── strategies.py          # Trading strategies
├── brokers.py             # Broker implementations
├── requirements.txt       # Python dependencies
├── setup.sh              # Initial setup script
├── deploy.sh             # Deployment script
└── neoalchemy.service    # Systemd service file
```

---

## 🔧 Troubleshooting

### **Bot won't start**
```bash
# Check service status
sudo systemctl status neoalchemy

# View detailed logs
sudo journalctl -u neoalchemy -n 50 --no-pager

# Check if process is running
ps aux | grep engines.py
```

### **Missing dependencies**
```bash
cd /root/NeoAlchemy
source venv/bin/activate
pip install -r requirements.txt
```

### **Database connection issues**
```bash
# Test database connection
psql -h localhost -U postgres -d trading_db

# Check if PostgreSQL is running
sudo systemctl status postgresql
```

### **Virtual environment not working**
```bash
# Recreate venv
cd /root/NeoAlchemy
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🔐 Security Notes

- ✅ `secrets` file is git-ignored (never committed)
- ✅ Service runs as root (consider creating dedicated user in production)
- ✅ Logs are stored locally (consider log rotation)

---

## 📊 Monitoring

### **Check bot is trading**
```bash
# View recent logs
tail -f /root/NeoAlchemy/logs/alchemy.log

# Check for recent trades
grep "OPEN\|CLOSE" /root/NeoAlchemy/logs/alchemy.log | tail -20
```

### **Check system resources**
```bash
# CPU and memory usage
htop

# Disk usage
df -h
```

---

## 🚨 Emergency Stop

If something goes wrong:

```bash
# Stop the bot immediately
sudo systemctl stop neoalchemy

# Or kill the process
pkill -f engines.py

# Close all positions (if needed)
python3 -c "
from brokers import LiveAlpacaBroker
broker = LiveAlpacaBroker()
broker.close_all_positions()
"
```

---

## 📝 Logs Location

- **Service logs**: `sudo journalctl -u neoalchemy`
- **Application logs**: `/root/NeoAlchemy/logs/alchemy.log`
- **Error logs**: `/root/NeoAlchemy/logs/bot-error.log`
- **Standard output**: `/root/NeoAlchemy/logs/bot.log`
