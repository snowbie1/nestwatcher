import json
import argparse
import requests
import sys
import discord

from datetime import datetime
from geojson import FeatureCollection, dumps

from utils.area import Area
from utils.analyze import analyze_nests
from utils.config import Config
from utils.logging import log
from utils.queries import Queries

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config", default="config/config.ini", help="Config file to use")
parser.add_argument("-t", "--hours", default=None, help="Hours since last migration")
args = parser.parse_args()
config_path = args.config
config = Config(config_path)
if not args.hours is None:
    config.hours_since_change = int(args.hours)

with open("config/areas.json", "r") as f:
    areas = json.load(f)
with open("config/settings.json", "r") as f:
    settings = json.load(f)
with open("config/discord.json", "r") as f:
    discord_template = json.load(f)

discord_webhook = False
discord_message = False

defaults = {
    "min_pokemon": 9,
    "min_spawnpoints": 2,
    "min_average": 0.5,
    "scan_hours_per_day": 24,
    "discord": ""
}
settings_defaults = [s for s in settings if s.get("area") == "DEFAULT"]
if len(settings_defaults) > 0:
    settings_defaults = settings_defaults[0]
else:
    settings_defaults = {}
for k, v in defaults.items():
    defaults[k] = settings_defaults.get(k, v)

for area in areas:
    if area["name"] not in [s["area"] for s in settings]:
        settings.append({"area": area["name"]})
area_settings = {}
for setting in settings:
    area_settings[setting["area"]] = {}
    for k, v in defaults.items():
        area_settings[setting["area"]][k] = setting.get(k, v)

for setting in area_settings.values():
    if isinstance(setting["discord"], str):
        if "webhooks" in setting["discord"]:
            discord_webhook = True
    elif isinstance(setting["discord"], int):
        discord_message = True

# Event Data

event_mons = []
event = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/info/events/active.json").json()
if datetime.strptime(event["end"], "%Y-%m-%d %H:%M") > datetime.now():
    log.success(f"Found ongoing event: {event['name']}")
    log.debug(event)
    for mon in event["details"]["spawns"]:
        try:
            event_mons.append(mon.split("_")[0])
        except:
            pass
    log.debug(f"event mons: {event_mons}")
else:
    log.info("No ongoing event found")

# Getting nesting species

nesting_mons = requests.get("https://pogoapi.net/api/v1/nesting_pokemon.json").json().keys()
nest_mons = [m for m in nesting_mons if m not in event_mons]
log.info("Got all nesting species")
log.debug(nest_mons)

# DB
log.info("Establishing DB connection and deleting current nests")
queries = Queries(config)
#queries.nest_delete()

all_features = []
full_areas = []
for i, area in enumerate(areas):
    area_ = Area(area, area_settings[area["name"]])
    nests = analyze_nests(config, area_, nest_mons, queries)
    area_.nests = nests
    full_areas.append(area_)

    for nest in nests:
        all_features.append(nest.feature)

with open(config.json_path, "w+") as file_:
    file_.write(dumps(FeatureCollection(all_features), indent=4))
    log.success("Saved Geojson file")
queries.close()

# Discord stuff
if discord_message:
    bot = discord.Client()

    @bot.event
    async def on_ready():
        for area in full_areas:
            d = area.settings["discord"]
            if isinstance(d, int):
                channel = await bot.fetch_channel(d)
                found = False
                async for message in channel.history():
                    if message.author == bot.user:
                        found = True
                        break
                embed = discord.Embed().from_dict(area.get_nest_text(discord_template, config.language))
                if found:
                    await message.edit(embed=embed)
                else:
                    await channel.send(embed=embed)
        await bot.logout()

    bot.run(config.discord_token)