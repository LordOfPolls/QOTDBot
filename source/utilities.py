import asyncio
import binascii
import logging
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import aiofiles
import aiohttp
import colorlog
import discord
import numpy as np
import pytz
import scipy.cluster
from PIL import Image
from colorlog import ColoredFormatter
from discord_slash.utils import manage_commands
from tzlocal import get_localzone

import source.pagination as pagination

paginator = pagination

from discord.ext import commands

thread_pool = ThreadPoolExecutor(max_workers=2)  # a thread pool

discordCharLimit = 2000


def getLog(filename, level=logging.DEBUG) -> logging:
    """ Sets up logging, to be imported by other files """
    streamHandler = colorlog.StreamHandler()
    streamFormatter = ColoredFormatter(
        "{asctime} {log_color}|| {levelname:^8} || {name:^11s} || {reset}{message}",
        datefmt="%H:%M:%S",
        reset=True,
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_yellow',
        },
        secondary_log_colors={},
        style='{'
    )

    streamHandler.setLevel(level)
    streamHandler.setFormatter(streamFormatter)

    _log = colorlog.getLogger(filename)

    _log.addHandler(streamHandler)
    _log.setLevel(logging.DEBUG)
    return _log


log = getLog("utils")


class colours:
    good = 0x00A300
    warning = 0xF1C232
    neutral = 0x00CCCC
    bad = 0xA30000


def defaultEmbed(colour=discord.Colour.blurple(), title=None):
    embed = discord.Embed(colour=colour, title=title)
    return embed


def getToken():
    try:
        file = open("data/token.pkl", "rb")
        token = pickle.load(file)
    except:  # if it cant load the token, ask for one, and then pickle it
        file = open("data/token.pkl", "wb")
        token = input("Input Discord Token: ").strip()
        pickle.dump(token, file)
    file.close()
    return token


def getDiscordBotsToken():
    try:
        file = open("data/DBtoken.pkl", "rb")
        token = pickle.load(file)
    except:  # if it cant load the token, ask for one, and then pickle it
        file = open("data/DBtoken.pkl", "wb")
        token = input("Input Discord Token: ").strip()
        pickle.dump(token, file)
    file.close()
    return token


async def getDominantColour(bot, imageURL):
    """Returns the dominant colour of an image from URL"""

    def blocking(imageDir):
        """This is the actual MEAT that gets the dominant colour,
        it is fairly computationally intensive, so i spin up a new thread
        to avoid blocking the main bot thread"""
        # log.debug("Reading image...")
        im = Image.open(imageDir)

        im = im.resize((100, 100), Image.NEAREST)

        ar = np.asarray(im)
        shape = ar.shape
        ar = ar.reshape(np.product(shape[:2]), shape[2]).astype(float)

        # log.debug("Finding Clusters")
        codes, dist = scipy.cluster.vq.kmeans(ar, 5)

        # log.debug("Clusters found")
        vecs, dist = scipy.cluster.vq.vq(ar, codes)  # assign codes
        counts, bins = np.histogram(vecs, len(codes))  # count occurrences

        # log.debug("Processing output")
        index_max = np.argmax(counts)  # find most frequent
        peak = codes[index_max]
        c = binascii.hexlify(bytearray(int(c) for c in peak)).decode('ascii')
        return c

    async with aiohttp.ClientSession() as session:
        async with session.get(imageURL) as r:
            # Asynchronously get image from url
            if r.status == 200:
                name = imageURL.split("/")[-1]
                f = await aiofiles.open(name, mode="wb")
                await f.write(await r.read())
                await f.close()

                loop = bot.loop
                colour = await loop.run_in_executor(thread_pool, blocking(name))
                os.unlink(name)
                colour = tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))
                colour = (colour[0] << 16) + (colour[1] << 8) + colour[2]
                return colour
    return None


def createBooleanOption(name, description="Yes or no", required=False) -> dict:
    """Creates a boolean slash option that aliases true/false to yes/no for user experience"""
    option = manage_commands.create_option(
        name=name,
        description=description,
        option_type=str,
        required=required,
        choices=[
            manage_commands.create_choice("True", "Yes"),
            manage_commands.create_choice("False", "No")]
    )
    return option


async def YesOrNoReactionCheck(ctx: commands.Context, message: discord.Message):
    """Adds a yes or no reaction poll to a message, and returns the result"""

    def check(reaction, user):
        return int(user.id) == int(ctx.author.id) \
               and (str(reaction.emoji) == "👍" or str(reaction.emoji) == "👎") \
               and reaction.message.id == message.id

    await message.add_reaction("👍")
    await message.add_reaction("👎")

    try:
        reaction, user = await ctx.bot.wait_for('reaction_add', timeout=60, check=check)
    except asyncio.TimeoutError:
        return
    else:
        try:
            await message.clear_reactions()
        except:
            pass
        if str(reaction.emoji) == "👍":
            return True
        else:
            return False


async def waitForChannelMention(ctx: commands.Context, message: discord.Message) -> (None or discord.TextChannel):
    """
    Waits for the original author to reply with a channel mention
    :param ctx:
    :param message:
    :return: the channel, or a None
    """

    def check(m: discord.Message):
        if m.author == ctx.author and m.channel == ctx.channel:
            if m.channel_mentions:
                return m.channel_mentions[0]

    try:
        output = await ctx.bot.wait_for('message', check=check)
    except asyncio.TimeoutError:
        return None
    return output.channel_mentions[0]


async def waitForMessageFromAuthor(ctx: commands.Context) -> (None or discord.Message):
    """
    Waits for a reply from the original author
    :param ctx:
    :return: the reply, or None
    """

    def check(m: discord.Message):
        if m.author == ctx.author and m.channel == ctx.channel:
            return True

    try:
        output = await ctx.bot.wait_for('message', check=check)
    except asyncio.TimeoutError:
        return None
    return output


async def checkPermsInChannel(member: discord.Member, channel: discord.TextChannel) -> bool:
    """Checks if the passed member has the following perms
    send messages, add reactions, manage messages, and embed links"""
    perms = member.permissions_in(channel)
    if perms.send_messages and perms.add_reactions and perms.manage_messages and perms.embed_links:
        return True
    return False


def convertTime(inputTimezone: str, hour: int) -> datetime:
    """
    Converts an input time from timezone to a local time
    :param inputTimezone: a string of the input timezone
    :param hour: the hour in question
    :return: datetime
    """
    local = str(get_localzone())
    time = datetime.utcnow()

    naiveTime = datetime.strptime(f"{time.year}-{time.month}-{time.day} {hour}:00", "%Y-%m-%d %H:%M")
    naiveTime = pytz.timezone(inputTimezone).localize(naiveTime)

    localTime = naiveTime.astimezone(pytz.timezone(local))
    return localTime
