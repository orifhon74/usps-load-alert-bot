import os
import re
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

# Session file will be created after first login
client = TelegramClient("listener_session", API_ID, API_HASH)

# Extract lines like: 📍 LOUISVILLE, KY
LOC_RE = re.compile(r"📍\s*([A-Z][A-Z\s\.\'-]+?),\s*([A-Z]{2})")

@client.on(events.NewMessage(chats=CHANNEL_USERNAME))
async def on_new_message(event):
    text = event.raw_text or ""
    locs = LOC_RE.findall(text)

    if not locs:
        return

    print("\n=== NEW LOAD ===")
    for city, st in locs:
        print(f"{city.strip().title()}, {st}")

async def main():
    print(f"Listening to @{CHANNEL_USERNAME} ...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    client.start()
    client.loop.run_until_complete(main())