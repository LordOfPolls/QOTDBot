import discord
import asyncio
from discord_slash import SlashContext
from source import utilities
import discord_slash

log = utilities.getLog("checks")


async def checkAll(ctx: SlashContext) -> bool:
    """Checks all checks and gives user feedback"""
    botPerms = ctx.guild.get_member(ctx.bot.user.id).permissions_in(ctx.channel)
    if not botHasPerms(ctx):
        log.debug("Rejecting Command: Bot lacks perms")
        if botPerms.send_messages:
            await ctx.respond()
            await ctx.send("Sorry, I dont have the permissions i need in this channel\n"
                           "I need: Send and Read Messages, add reactions, manage messages, and embed links")
        return False

    if not userHasPerms(ctx):
        log.debug("Rejecting Command: User lacks perms")
        await ctx.respond(eat=True)
        await ctx.send("Sorry, you don't have the permissions required to use this.\n "
                       "You need ``manage_server`` or higher", hidden=True)
        return False

    if not await checkGuildIsSetup(ctx):
        if ctx.subcommand_name != "simple":
            log.debug("Rejecting Command: Guild not setup")
            await ctx.respond()
            await ctx.send("This server has not run the initial setup yet\n"
                           "Someone with manage_server perms or higher needs to run"
                           "``/setup simple`` to get started")
            return False
    return True


async def checkUserAll(ctx) -> bool:
    botPerms = ctx.guild.get_member(ctx.bot.user.id).permissions_in(ctx.channel)
    if not botHasPerms(ctx):
        log.debug("Rejecting Command: Bot lacks perms")
        if botPerms.send_messages and botPerms.read_messages:
            await ctx.respond()
            await ctx.send("Sorry, I dont have the permissions i need in this channel"
                           "I need: Send and Read Messages, add reactions, manage messages, and embed links")
            return False
    if not await checkGuildIsSetup(ctx):
        log.debug("Rejecting Command: Guild not setup")
        await ctx.respond()
        await ctx.send("This server has not run the initial setup yet\n"
                       "Someone with manage_server perms or higher needs to run"
                       "``/setup simple`` to get started")
        return False
    return True


def botHasPerms(ctx: SlashContext) -> bool:
    """Checks if the bot has the following permissions
    Can send messages
    Can read messages
    Can add reactions
    Can manage messages
    Can embed links
    """
    bot: discord.Member = ctx.guild.get_member(ctx.bot.user.id)
    if bot:
        perms = bot.permissions_in(ctx.channel)
        return perms.send_messages and \
               perms.read_messages and \
               perms.manage_messages and \
               perms.embed_links and \
               perms.add_reactions
    return False


def userHasPerms(ctx: SlashContext) -> bool:
    """Checks if the message author has manage_messages or higher"""
    author = ctx.author
    if author.id == ctx.guild.owner_id:
        return True

    if author.permissions_in(ctx.channel).manage_guild:
        return True

    return False


async def checkGuildIsSetup(ctx) -> bool:
    """Makes sure all the basic information is set"""
    try:
        guildData = await ctx.bot.db.execute(
            f"SELECT * FROM QOTDBot.guilds WHERE guildID = '{ctx.guild.id}'",
            getOne=True
        )
        if guildData['qotdChannel'] is None or \
                guildData['timeZone'] is None or \
                guildData['sendTime'] is None:
            return False
        return True
    except TypeError:
        log.warning(f"{ctx.guild.id}:: Not present in guild table, creating entry")
        await ctx.bot.db.execute(
            f"INSERT INTO QOTDBot.guilds SET guildID = '{ctx.guild.id}', prefix = '/' "
            f"ON DUPLICATE KEY UPDATE guildID = '{ctx.guild.id}'"
        )
        return False
