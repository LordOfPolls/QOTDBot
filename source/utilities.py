import asyncio
import os

import discord
import colorlog
import logging
from PIL import Image
import numpy as np
import scipy.cluster
import binascii
import pickle
import aiohttp
import aiofiles
from colorlog import ColoredFormatter
from concurrent.futures import ThreadPoolExecutor
from discord_slash.utils import manage_commands
from datetime import datetime
from tzlocal import get_localzone
import pytz
import source.pagination as pagination

paginator = pagination

from discord.ext import commands

thread_pool = ThreadPoolExecutor(max_workers=2)  # a thread pool

discordCharLimit = 2000


class colours:
    good = 0x00A300
    warning = 0xF1C232
    neutral = 0x00CCCC
    bad = 0xA30000


def defaultEmbed(colour=discord.Colour.blurple(), title=None):
    embed = discord.Embed(colour=colour, title=title)
    return embed


def getLog(filename, level=logging.DEBUG) -> logging:
    """ Sets up logging, to be imported by other files """
    streamHandler = colorlog.StreamHandler()
    fileHandler = logging.FileHandler('data/logs/bot.log', encoding="utf-8")
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
    fileFormatter = logging.Formatter("%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
                                      datefmt='%Y-%m-%d %H:%M:%S')

    fileHandler.setLevel(logging.DEBUG)
    streamHandler.setLevel(level)
    streamHandler.setFormatter(streamFormatter)
    fileHandler.setFormatter(fileFormatter)

    log = colorlog.getLogger(filename)

    log.addHandler(streamHandler)
    log.addHandler(fileHandler)
    log.setLevel(logging.DEBUG)
    return log


def getPrefix(_bot: commands.Bot, message: discord.message):
    """Dictates the prefix for the bot"""
    default = ">"
    if not message.guild:
        # If used in dm
        if message.content.startswith(default):
            return default
        if message.content.startswith(_bot.user.mention):
            return commands.when_mentioned(_bot, message)
        return ""

    else:
        if message.content.startswith(default):
            return default
        if message.content.startswith(_bot.user.mention):
            return commands.when_mentioned(_bot, message)
    return default


def actuallyReady(_bot):
    if _bot.uberReady:
        return True
    else:
        return False


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


async def acknowledge(ctx):
    try:
        await ctx.respond()
    except discord.NotFound:
        pass

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


async def checkGuildIsSetup(ctx):
    """Makes sure all the basic information is set"""
    guildData = await ctx.bot.db.execute(
        f"SELECT * FROM QOTDBot.guilds WHERE guildID = '{ctx.guild.id}'",
        getOne=True
    )
    embed = defaultEmbed(title="Config Error", colour=discord.Colour.orange())
    embed.set_footer(text="An admin needs to run \"/setup simple\" to set up your server")
    if guildData['qotdChannel'] is None:
        embed.description = "You have not set a qotd channel"
        await ctx.send(embed=embed)
        return False
    if guildData['timeZone'] is None:
        embed.description = "You have not set your timezone"
        await ctx.send(embed=embed)
        return False
    if guildData['sendTime'] is None:
        embed.description = "You have not set a send time"
        await ctx.send(embed=embed)
        return False
    return True


async def slashCheck(ctx):
    if ctx.guild:
        if ctx.author.guild_permissions.manage_guild:
            return True
        await ctx.send("Sorry you cant use this command. You need manage_server or higher")
    else:
        await ctx.send("Sorry, you can't use that here")
    return False


async def getMessage(cog, messageID: int, channel: discord.TextChannel) -> (discord.Message, None):
    """Gets a message using the id given"""
    for message in cog.Bot.cached_messages:
        # Check if the message is in the cache to save querying discord
        if message.id == messageID:
            return message

    # try and find the message in the channel
    o = discord.Object(id=messageID + 1)
    msg = await channel.history(limit=1, before=o).next()
    if messageID == msg.id:
        return msg
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
