import asyncio
import logging
from datetime import datetime

import aiohttp
import discord
import discord_slash
import discord_slash.model as slashModel
from discord.ext import commands
from discord_slash import SlashCommand, SlashContext, error

from . import utilities, dataclass, checks, slashParser

log = utilities.getLog("Bot")
intents = discord.Intents.default()
intents.members = True

bot = dataclass.Bot(
    command_prefix="/",
    description="Query",
    case_insensitive=True,
    intents=intents,
    cogList=[
        "source.cogs.qotd",
        "source.cogs.config",
        "source.cogs.polls"
    ],
    help_command=None
)
slash = SlashCommand(bot, sync_commands=True)  # register a slash command system
if bot.cogList:
    log.info("Mounting cogs...")
    for cog in bot.cogList:
        log.info(f"Mounting {cog}...")
        bot.load_extension(cog)
else:
    log.warning("No cogs to load!")

slash.logger = utilities.getLog("slashAPI", logging.DEBUG)
perms = "24640"


def run():
    log.info("Connecting to discord...")
    bot.run(utilities.getToken(), bot=True, reconnect=True)


async def startupTasks():
    """All the tasks the bot needs to run when it starts up"""
    log.debug("Running startup tasks...")
    bot.appInfo = await bot.application_info()
    bot.startTime = datetime.now()
    await bot.change_presence(status=discord.Status.do_not_disturb, activity=discord.Game("Startup"))

    log.info("Establishing connection to database...")
    try:
        await bot.db.connect()
    except Exception as e:
        log.error(e)

    log.info("Running cog setup tasks")
    for cog in bot.cogs:
        _c = bot.get_cog(cog)
        if hasattr(_c, "setup"):
            await _c.setup()
    asyncio.create_task(statsUpdate())


@bot.event
async def on_ready():
    """Called when the bot is ready"""
    if not bot.startTime:
        await startupTasks()
    log.info("INFO".center(40, "-"))
    log.info(f"Logged in as       : {bot.user.name} #{bot.user.discriminator}")
    log.info(f"User ID            : {bot.user.id}")
    log.info(f"Start Time         : {bot.startTime.ctime()}")
    log.info(f"DB Connection Type : {'Tunneled' if bot.db.tunnel else 'Direct'}")
    log.info(f"Server Count       : {len(bot.guilds)}")
    log.info(f"Cog Count          : {len(bot.cogs)}")
    log.info(f"Command Count      : {len(slash.commands)}")
    log.info(f"Discord.py Version : {discord.__version__}")
    log.info("END-INFO".center(40, "-"))


async def statsUpdate():
    if not bot.shouldUpdateBL:
        return False
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
            log.debug("Updated DiscordBotList.com")
        else:
            log.error(f"Failed to update DiscordBotList.com: {resp.status}: {resp.reason}")
            if resp.status == 401:
                log.warning("Disabling bot list updates for this session")
                bot.shouldUpdateBL = False


@commands.check(checks.botHasPerms)
@slash.slash(**slashParser.getDecorator("help"))
async def helpCMD(ctx):
    if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
        raise discord_slash.error.CheckFailure
    await ctx.respond()

    _commands = slash.commands
    subcommands = slash.subcommands
    embed = utilities.defaultEmbed(title="")
    embed.set_author(name="Command List", icon_url=bot.user.avatar_url)

    for key in _commands:
        cmd: slashModel.CommandObject = _commands[key]
        if cmd.has_subcommands:
            subCMDs = subcommands[cmd.name]
            for _cmdKey in subCMDs:
                subCMD: slashModel.SubcommandObject = subCMDs[_cmdKey]
                embed.add_field(name=f"{cmd.name} {subCMD.name}", value=subCMD.description, inline=True)
        else:
            embed.add_field(name=cmd.name, value=cmd.description, inline=False)
    embed.add_field(name="For assistance join my server:", value="https://discord.gg/V82f6HBujR", inline=False)
    embed.set_footer(
        text="All of the commands are integrated into your servers slash commands, to access them type `/`")
    await ctx.send(embed=embed)


@commands.check(checks.botHasPerms)
@slash.slash(**slashParser.getDecorator("privacy"))
async def privacy(ctx):
    if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
        raise discord_slash.error.CheckFailure
    await ctx.respond()
    data = open("data/privacy.md", "r").read()
    data = data.replace("[@TheBot]", bot.user.mention)
    await ctx.send(data, hidden=not await bot.is_owner(ctx.author))


@commands.check(checks.botHasPerms)
@slash.slash(**slashParser.getDecorator("ping"))
async def ping(ctx):
    if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
        raise discord_slash.error.CheckFailure
    await ctx.respond()
    await ctx.send(f"Pong: {bot.latency * 1000:.2f}ms")


@commands.check(checks.botHasPerms)
@slash.slash(**slashParser.getDecorator("invite"))
async def cmdInvite(ctx):
    if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
        raise discord_slash.error.CheckFailure
    await ctx.respond()
    await ctx.send(f"https://discord.com/oauth2/authorize?client_id={bot.user.id}"
                   f"&permissions={perms}&scope=applications.commands%20bot")


@commands.check(checks.botHasPerms)
@slash.slash(**slashParser.getDecorator("server"))
async def cmdServer(ctx):
    if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
        raise discord_slash.error.CheckFailure

    await ctx.respond()
    await ctx.send("https://discord.gg/V82f6HBujR")


@bot.command(name="Shutdown", brief="Shuts down the bot")
async def cmdShutdown(ctx: commands.Context):
    if await bot.is_owner(ctx.author):
        log.warning("Shutdown called")
        await ctx.send("Shutting down 🌙")
        await bot.close()


@bot.command(name="setname", brief="Renames the bot")
async def cmdSetName(ctx: commands.Context, name: str):
    if await bot.is_owner(ctx.author):
        await bot.user.edit(username=name)


@bot.command(name="setAvatar", brief="Sets the bots avatar")
async def cmdSetAvatar(ctx: commands.Context):
    if await bot.is_owner(ctx.author):
        if ctx.message.attachments:
            photo = ctx.message.attachments[0].url
            async with aiohttp.ClientSession() as session:
                async with session.get(photo) as r:
                    if r.status == 200:
                        data = await r.read()
                        try:
                            await bot.user.edit(avatar=data)
                            return await ctx.send("Set avatar, how do i look?")
                        except discord.HTTPException:
                            await ctx.send("Unable to set avatar")
                            return
        await ctx.send("I cant read that")


@bot.command(name="status", brief="Status of the bot")
async def cmdStatus(ctx: commands.Context):
    if await bot.is_owner(ctx.author):
        # grab DB data
        setupGuilds = len(await bot.db.execute('SELECT * FROM QOTDBot.guilds WHERE timeZone IS NOT NULL'))
        totalQuestions = await bot.db.execute(
            "SELECT COUNT(*) FROM QOTDBot.questions ", getOne=True
        )
        totalLog = await bot.db.execute(
            "SELECT COUNT(*) FROM QOTDBot.questionLog ", getOne=True
        )

        # get qotd cog's data
        scheduledTasks = "Error, could not determine"
        cog = bot.get_cog("QOTD")
        if hasattr(cog, "scheduler"):
            scheduledTasks = len(cog.scheduler.get_jobs())

        # get uptime and human format it
        uptime = datetime.now() - bot.startTime
        days, remainder = divmod(uptime.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days != 0:
            days = f"{days} day{'s' if days > 1 else ''}, "
        else:
            days = ""

        message = [
            "```css",
            f"Logged in as       : '{bot.user.name} #{bot.user.discriminator}'",
            f"User ID            : '{bot.user.id}'",
            f"Start Time         : '{bot.startTime.ctime()}'",
            f"Uptime             : '{days}{round(hours):02}:{round(minutes):02}:{round(seconds):02}'",
            f"DB Connection Type : '{'Tunneled' if bot.db.tunnel else 'Direct'}'",
            f"DB Operations      : '{bot.db.operations}'",
            f"Stored Questions   : '{totalQuestions['COUNT(*)']}'",
            f"Question Log Size  : '{totalLog['COUNT(*)']}'",
            f"Scheduled Tasks    : '{scheduledTasks}'",
            f"Server Count       : '{len(bot.guilds)}'",
            f"Setup Servers      : '{setupGuilds}'",
            f"Cog Count          : '{len(bot.cogs)}'",
            f"Command Count      : '{len(slash.commands)}'",
            f"Discord.py Version : '{discord.__version__}'",
            "```"
        ]
        message.insert(1, "BOT INFO".center(len(max(message, key=len)), "-"))
        message.insert(len(message) - 1, "END BOT INFO".center(len(max(message, key=len)), "-"))
        await ctx.send("\n".join(message))


@bot.event
async def on_slash_command(ctx: SlashContext):
    subcommand = ""
    try:
        if ctx.subcommand_name:
            subcommand = ctx.subcommand_name
    except AttributeError:
        pass
    if ctx.guild:
        log.info(f"CMD - {ctx.guild.id}::{ctx.author.id}: {ctx.command} {subcommand}")
    else:
        log.info(f"CMD - Direct Message::{ctx.author.id}: {ctx.command} {subcommand}")


@bot.event
async def on_command_error(ctx, ex):
    return


@bot.event
async def on_slash_command_error(ctx, ex):
    if isinstance(ex, discord.errors.Forbidden):
        log.error(f"Missing permissions in {ctx.guild.name}")
        await ctx.send(f"**Error:** I am missing permissions.\n"
                       f"Please make sure i can access this channel, manage messages, embed links, and add reactions.")
    elif isinstance(ex, discord_slash.error.CheckFailure):
        log.debug(f"Ignoring command: check failure")
    else:
        log.error(ex)
        await ctx.send("An un-handled error has occurred, and has been logged, please try again later.\n"
                       "If this continues please use `/server` and report it in my server")


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Called when bot is added to a guild"""
    while not bot.is_ready():
        await asyncio.sleep(5)
    log.info(f"Joined Guild {guild.id}. {len([m for m in guild.members if not m.bot])} users")
    await statsUpdate()
    if guild.id == 110373943822540800:
        return

    await bot.db.execute(
        f"INSERT INTO QOTDBot.guilds SET guildID = '{guild.id}', prefix = '/' "
        f"ON DUPLICATE KEY UPDATE guildID = '{guild.id}'"
    )
    embed = utilities.defaultEmbed(title="Hello!")
    message = "[intro]\n" \
              "To get started, simply type `/setup simple` in the server " \
              "(note you will need manage_server perms or higher)\n\n" \
              "The bot **must** have the following permissions, or it will not function:\n" \
              "Send Messages, Add Reactions, Manage Messages, and Embed Links\n\n" \
              "For updates, issues, and changes, join my server: https://discord.gg/V82f6HBujR"
    embed.set_thumbnail(url=bot.user.avatar_url)
    me = guild.get_member(user_id=bot.user.id)
    try:
        # try and find a place that we can send our greeting
        # system channel -> general channel -> guild owner
        if guild.system_channel and \
                me.permissions_in(guild.system_channel).send_messages and \
                me.permissions_in(guild.system_channel).embed_links:

            embed.description = message.replace("[intro]", f"I am **{bot.user.name}**")
            embed.set_footer(text="this message was sent here as this is set as your system channel")

            await guild.system_channel.send(embed=embed)
            return log.debug("Sent greeting in system channel")

        elif "general" in str([c.name.lower() for c in guild.text_channels]):
            for channel in guild.text_channels:
                if "general" in channel.name.lower() and \
                        me.permissions_in(channel).send_messages and \
                        me.permissions_in(channel).embed_links:
                    embed.description = message.replace("[intro]", f"I am **{bot.user.name}**")
                    embed.set_footer(text="this message was sent here as I could not find a system channel, "
                                          "and this had \"general\" in the name")
                    await channel.send(embed=embed)
                    return log.debug("Sent greeting in general channel")

        embed.description = message.replace("[intro]",
                                            f"I am **{bot.user.name}**. I was just added to *{guild.name}*")
        embed.set_footer(
            text="this message was sent here as your server does not have a system channel "
                 "and a general channel could not be found")
        await guild.owner.send(embed=embed)
        return log.debug("Sent greeting in owner dm")

    except Exception as e:
        log.error(f"Error sending greeting message: {guild.id}::{e}")
    log.warning(f"Could not send greeting message in {guild.id}")


@bot.event
async def on_guild_remove(guild):
    while not bot.is_ready():
        await asyncio.sleep(5)
    if guild.id == 110373943822540800:
        return
    log.info(f"Left Guild {guild.id}| Purging data...")
    try:
        await bot.db.execute(
            f"DELETE FROM QOTDBot.questionLog WHERE guildID = '{guild.id}'"
        )
        await bot.db.execute(
            f"DELETE FROM QOTDBot.questions WHERE guildID = '{guild.id}'"
        )
        await bot.db.execute(
            f"DELETE FROM QOTDBot.guilds WHERE guildID = '{guild.id}'"
        )
        log.debug(f"{guild.id}:: Data Purged")
    except Exception as e:
        log.critical(f"FAILED TO PURGE DATA FOR {guild.id}: {e}")
    asyncio.create_task(statsUpdate())


@bot.event
async def on_member_join(member):
    if member.guild.id == 110373943822540800:
        return
    if not member.bot:
        log.debug("Member added event")
        asyncio.create_task(statsUpdate())


@bot.event
async def on_member_remove(member):
    if member.guild.id == 110373943822540800:
        return
    if not member.bot:
        log.debug("Member removed event")
        asyncio.create_task(statsUpdate())
