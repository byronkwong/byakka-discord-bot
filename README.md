# Snormax Restock Discord Bot

A Discord bot that monitors Best Buy product availability using the Snormax API and sends automated restock alerts.

## Features

- 🚨 **Real-time restock alerts** with priority-based notifications
- 📍 **Location-specific monitoring** using zip codes
- 🏪 **Store availability details** with stock quantities
- 🎯 **Priority system** (Top, High, Medium, Low)
- 📝 **JSON-based product management** for easy configuration
- 🔗 **Direct Snormax links** for quick stock checking

## Quick Start

### Prerequisites
- Python 3.11+
- Discord bot token
- Discord server with channel for notifications

### Local Setup
1. Clone the repository
2. Install dependencies:
   ```bash
   pip install discord.py aiohttp
   ```
3. Configure environment variables:
   ```bash
   BOT_TOKEN=your_discord_bot_token
   CHANNEL_ID=your_discord_channel_id
   USER_ID=your_discord_user_id
   ```
4. Update `products.json` with your desired products
5. Run the bot:
   ```bash
   python restock_bot.py
   ```

### Cloud Deployment (Railway)
1. Fork this repository
2. Deploy to [Railway.app](https://railway.app)
3. Set environment variables in Railway dashboard
4. Bot runs 24/7 automatically

## Commands

| Command | Description |
|---------|-------------|
| `!status [priority]` | Check current stock status |
| `!list [priority]` | Simple product list |
| `!listd [priority]` | Detailed product list with links |
| `!add [sku] [zip] [name]` | Add product to monitor |
| `!remove [sku] [zip]` | Remove product from monitoring |
| `!debug [sku] [zip]` | Debug API response |

## Configuration

Edit `products.json` to customize monitored products:

```json
[
  {
    "sku": "6540134",
    "zip_code": "90503",
    "name": "Product Name",
    "category": "Electronics",
    "set": "Product Line",
    "priority": "high"
  }
]
```

## Priority Levels

- 🔥 **TOP**: Highest priority with red alerts
- 🚨 **HIGH**: High priority with orange alerts  
- ⚠️ **MEDIUM**: Medium priority with green alerts
- 📝 **LOW**: Low priority with gray alerts

## Files

- `restock_bot.py` - Main bot application
- `products.json` - Product configuration
- `requirements.txt` - Python dependencies
- `Procfile` - Railway deployment config
- `runtime.txt` - Python version specification
