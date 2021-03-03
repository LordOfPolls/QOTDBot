import json
import os
import logging

from source import utilities

log = utilities.getLog("slashParser", level=40)


def read(name: str):
    """Read a json file and returns its information"""
    log.debug(f"Reading {name} from json")
    path = f"data/commands/{name}.json"
    if not os.path.isfile(path):
        log.error(f"{path} does not exist")
        raise FileNotFoundError

    data = json.load(open(path, "r"))
    return data


def getDecorator(name: str):
    """Get the decorator data for a command"""
    return read(name)['decorator']


def write(name: str, description: str, options: list = None, guild_ids: list = None, base=None):
    """Writes a basic command json file
    used in development"""
    data = {
        "decorator": {
            "name": name.lower(),
            "description": description,
            "options": options,
            "guild_ids": guild_ids
        }
    }
    if base:
        data['decorator']['base'] = base
    json.dump(data, open(f"{base + '.' if base else ''}{name}.json", "w"), indent=2)
    log.debug("wrote command data to json")
