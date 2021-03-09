import json
import os
import logging
from pprint import pprint

from discord_slash.utils import manage_commands

from source import utilities

log = utilities.getLog("slashParser", level=40)

path = "data/commands/"


def read(name: str):
    """Read a json file and returns its information"""
    log.debug(f"Reading {name} from json")
    _path = path + f"{name}.json"
    if not os.path.isfile(_path):
        log.error(f"{_path} does not exist")
        raise FileNotFoundError

    data = json.load(open(_path, "r"))
    return data


def getDecorator(name: str):
    """Get the decorator data for a command"""
    return read(name)['decorator']


def write(name: str, description: str, options: list = None, guild_ids: list = None, **kwargs):
    """Writes a basic command json fle
    Used in development"""
    # assure basic information

    # determine filename
    _path = f"{path}{name}"
    if kwargs['base']:
        _path += f".{kwargs['base']}"

    # create data
    data = {"decorator": {
        "name": name.lower(),
        "description": description,
        "options": options,
        "guild_ids": guild_ids
    }}
    for kw in kwargs:
        data["decorator"][kw] = kwargs[kw]

    # write to file
    json.dump(data, open(f"{_path}.json", "w"), indent=2)


write(name="test", description="blah", options=[
    manage_commands.create_option(name="opt1", description="some option", option_type=3, required=False,
                                  choices=[manage_commands.create_choice(value="yes", name="Yeah"),
                                           manage_commands.create_choice(value="no", name="nope")]),
    manage_commands.create_option(name="opt2", description="some option", option_type=4, required=False),
    manage_commands.create_option(name="opt2", description="some option", option_type=5, required=False),
],
      base="nah",
      guild_ids=[701347683591389185])
