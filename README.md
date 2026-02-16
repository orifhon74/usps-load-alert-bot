🚛 USPS Live Bid Route Alert Bot

A private Telegram bot that instantly notifies users when specific USPS Live Bid routes are posted, based on customizable origin and destination filters.

Built to eliminate manual monitoring and prevent missed load opportunities.

⸻

🎯 Purpose

Dispatchers and truckers often monitor the USPS Live Bid channel manually to catch relevant routes. This can require:
	•	Checking uploads late at night
	•	Constant refreshing
	•	Risk of missing rare or high-value routes

This bot automates that process.

It watches the channel 24/7 and immediately alerts users when a route matching their configured criteria appears.

⸻

⚙️ How It Works
	1.	The bot listens to the USPS Live Bid Telegram channel.
	2.	Users configure:
	•	One or more origin cities or states
	•	Destination state filters
	3.	When a new route is posted:
	•	The bot parses the route
	•	Checks it against user filters
	•	Instantly sends a Telegram alert if matched

There is no artificial delay. Alerts are triggered as soon as the route appears in the channel.

⸻

✨ Features
	•	✅ Instant route alerts (no polling delay)
	•	✅ Multiple origin cities or states per user
	•	✅ Destination state filtering
	•	✅ Private access control
	•	✅ Dockerized deployment
	•	✅ Persistent data storage (SQLite)
	•	✅ Lightweight VPS friendly (tested on low-cost server)

⸻

🧠 Real-World Use Case

This bot was originally built to help a dispatcher who had to monitor uploads even after working hours.

In one case, only three relevant routes were posted in a day and were missed due to manual monitoring limits.

The bot ensures:
	•	No missed uploads
	•	No after-hours manual checking
	•	Immediate awareness of relevant routes

⸻

🔐 Access Model

The bot is currently private and invite-only.

Unauthorized users are blocked automatically.

Access control allows gradual onboarding and prevents system overload.

⸻

🖥️ Tech Stack
	•	Python (async architecture)
	•	python-telegram-bot / Telethon
	•	SQLite (via aiosqlite)
	•	Docker + Docker Compose
	•	VPS deployment (tested on low-resource instance)


⸻

🐳 Deployment

The bot runs as a Docker service:
```
services:
  usps-bot:
    build: .
    container_name: usps-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/data
```
Start:
```
docker-compose up -d
```
The service runs continuously and auto-restarts if the server reboots.

⸻

📈 Future Plans

Potential future enhancements may include:
	•	Usage tiers
	•	Expanded route management
	•	Multi-user dispatcher configurations
	•	Admin tools

Core functionality will remain focused on instant route awareness.

⸻

⚠️ Disclaimer

This bot is not affiliated with USPS.
It operates by monitoring publicly available Telegram route postings.

⸻

📬 Contact

Access is currently private.
If interested, contact the developer directly.
