import logging
from pprint import pprint

import aiohttp
import discord
import asyncio
from discord.ext import commands
import discord_slash.model as slshModel
from discord_slash import SlashCommand, SlashContext
from discord_slash.utils import manage_commands
from datetime import datetime

import asyncio

from . import utilities, dataclass

log = utilities.getLog("Bot")
intents = discord.Intents.default()
intents.members = True

bot = dataclass.Bot(
    command_prefix="/",
    description="QOTD Bot",
    case_insensitive=True,
    intents=intents,
    cogList=[
        "source.cogs.qotd",
        "source.cogs.config"
    ]
)
bot.remove_command("help")
slash = SlashCommand(bot, sync_on_cog_reload=True)  # register a slash command system
slash.logger = utilities.getLog("slashAPI", logging.DEBUG)
perms = "24640"


def run():
    log.info("Connecting to discord...")
    bot.run(utilities.getToken(), bot=True, reconnect=True)


@bot.event
async def on_ready():
    """Called when the bot is ready"""
    log.info(f"Logged in as: {bot.user.name} #{bot.user.id}")
    bot.appInfo = await bot.application_info()
    bot.startTime = datetime.now()
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=discord.Game("Startup"))

    log.info("Establishing connection to database...")
    try:
        await bot.db.connect()
    except Exception as e:
        log.error(e)

    if bot.cogList:
        log.info("Mounting cogs...")
        for cog in bot.cogList:
            log.info(f"Mounting {cog}...")
            bot.load_extension(cog)
    else:
        log.warning("No cogs to load!")

    try:
        await slash.sync_all_commands()
    except discord.HTTPException:
        await asyncio.sleep(30)
        await slash.sync_all_commands()
    await statsSystem()


async def statsSystem():
    discordBots = f"https://discordbotlist.com/api/v1/bots/{bot.user.id}/stats"

    dbHeaders = {
        'Authorization': utilities.getDiscordBotsToken(),
    }

    async with aiohttp.ClientSession(headers=dbHeaders) as session:
        totalUsers = 0
        for g in bot.guilds:
            totalUsers += len([m for m in g.members if not m.bot])
        dBotPayload = {
            'guilds': len(bot.guilds),
            'users': totalUsers
        }

        resp = await session.post(discordBots, data=dBotPayload)
        if resp.status == 200:
            log.info("Updated discordbots stats")
        else:
            log.error(f"Failed to update discordbots stats: {resp.status}: {resp.reason}")


@slash.slash(name="help", description="A helpful message")
async def helpCMD(ctx):
    await ctx.respond()
    commands = slash.commands
    subcommands = slash.subcommands
    embed = utilities.defaultEmbed(title="")
    embed.set_author(name="Command List", icon_url=bot.user.avatar_url)
    pprint(subcommands)
    for key in commands:
        cmd: slshModel.CommandObject = commands[key]
        if cmd.has_subcommands:
            subcmds = subcommands[cmd.name]
            for _cmdKey in subcmds:
                subcmd: slshModel.SubcommandObject = subcmds[_cmdKey]
                embed.add_field(name=f"{cmd.name} {subcmd.name}", value=subcmd.description, inline=True)
        else:
            embed.add_field(name=cmd.name, value=cmd.description, inline=False)
    embed.set_footer(
        text="All of the commands are integrated into your servers slash commands, to access them type ``/``")
    await ctx.send(embed=embed)


@slash.slash(name="ping", description="ping me")
async def ping(ctx):
    await ctx.respond()
    await ctx.send(f"Pong: {bot.latency * 1000:.2f}ms")


@slash.slash(name="invite", description="Get an invite link for the bot")
async def cmdInvite(ctx):
    await ctx.respond()
    await ctx.send(f"https://discord.com/oauth2/authorize?client_id={bot.user.id}"
                   f"&permissions={perms}&scope=applications.commands%20bot")


@slash.slash(name="server", description="Get an invite to the bots server")
async def cmdServer(ctx):
    await ctx.respond()
    await ctx.send("https://discord.gg/V82f6HBujR")


# @bot.command(name="setAvatar", brief="Sets the bots avatar")
# async def cmdSetAvatar(ctx: commands.Context):
#     if ctx.message.attachments:
#         photo = ctx.message.attachments[0].url
#         async with aiohttp.ClientSession() as session:
#             async with session.get(photo) as r:
#                 if r.status == 200:
#                     data = await r.read()
#                     try:
#                         await bot.user.edit(avatar=data)
#                         return await ctx.send("Set avatar, how do i look?")
#                     except discord.HTTPException:
#                         await ctx.send("Unable to set avatar")
#                         return
#     await ctx.send("I cant read that")


@bot.event
async def on_slash_command(ctx: SlashContext):
    subcommand = ""
    try:
        if ctx.subcommand:
            subcommand = ctx.subcommand
    except AttributeError:
        pass
    if ctx.guild:
        log.info(f"CMD - {ctx.guild.id}::{ctx.author.id}: {ctx.command} {subcommand}")
    else:
        log.info(f"CMD - Direct Message::{ctx.author.id}: {ctx.command} {subcommand}")


@bot.event
async def on_command_error(ctx, ex):
    if isinstance(ex, discord.ext.commands.CommandNotFound):
        return
    log.error(f"Error in {ctx.guild.id}: {ex}")

@bot.event
async def on_slash_command_error(ctx, ex):
    if isinstance(ex, discord.errors.Forbidden):
        log.error(f"Missing permissions in {ctx.guild.name}")
        await ctx.send(f"**Error:** I am missing permissions.\n"
                       f"Please make sure i can access this channel, manage messages, embed links, and add reactions.")
    else:
        log.error(ex)
        await ctx.send("An un-handled error has occurred, and has been logged, please try again later.\n"
                       "If this continues please use ``/server`` and report it in my server")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Called when bot is added to a guild"""
    log.info(f"Joined Guild {guild.id}")
    await statsSystem()

    await bot.db.execute(
        f"INSERT INTO QOTDBot.guilds SET guildID = '{guild.id}', prefix = '/' "
        f"ON DUPLICATE KEY UPDATE guildID = '{guild.id}'"
    )
    try:
        await guild.owner.send(f"Hi there, I am **QOTDBot**. I was just added to your server ({guild.name})\n"
                               f"To get started, simply type ``/setup simple`` in your server")
        log.debug("Sent join dm to guild owner")
        return
    except:
        if guild.system_channel:
            try:
                await guild.system_channel.send("Hi there!\nI am **QOTDBot**\n"
                                                "To get started, simply type ``/setup simple`` (you will need manage server perms)")
                log.debug("Send join message to system channel")
                return
            except:
                pass
    log.warning(f"Could not send greeting message in {guild.id}")


@bot.event
async def on_guild_remove(guild):
    log.info(f"Left Guild {guild.id}")
    await statsSystem()


@bot.event
async def on_member_join(member):
    log.info("Member added event")
    await statsSystem()


@bot.event
async def on_member_remove(member):
    log.info("Member removed event")
    await statsSystem()