import io
import textwrap
import traceback
from contextlib import redirect_stdout
from datetime import datetime

import aiohttp
import discord
import discord_slash
from discord.ext import commands
from discord_slash import cog_ext, SlashContext, error
import discord_slash.model as slashModel

from source import utilities, dataclass, jsonManager, checks

log = utilities.getLog("Cog::base")


class Base(commands.Cog):
    """Configuration commands"""

    def __init__(self, bot: dataclass.Bot):
        self.bot = bot

        self.slash = bot.slash

        self.emoji = "🚩"

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("help"))
    async def helpCMD(self, ctx):
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()

        _commands = self.slash.commands
        subcommands = self.slash.subcommands
        embed = utilities.defaultEmbed(title="")
        embed.set_author(name="Command List", icon_url=self.bot.user.avatar_url)

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
    @cog_ext.cog_slash(**jsonManager.getDecorator("privacy"))
    async def privacy(self, ctx):
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        data = open("data/privacy.md", "r").read()
        data = data.replace("[@TheBot]", self.bot.user.mention)
        await ctx.send(data, hidden=not await self.bot.is_owner(ctx.author))

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("ping"))
    async def ping(self, ctx):
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.send(f"Pong: {self.bot.latency * 1000:.2f}ms")

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("invite"))
    async def cmdInvite(self, ctx):
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.send(f"https://discord.com/oauth2/authorize?client_id={self.bot.user.id}"
                       f"&permissions={self.bot.perms}&scope=applications.commands%20bot")

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("server"))
    async def cmdServer(self, ctx):
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure

        await ctx.send("https://discord.gg/V82f6HBujR")

    @commands.command(name="Shutdown", brief="Shuts down the bot")
    async def cmdShutdown(self, ctx: commands.Context):
        if await self.bot.is_owner(ctx.author):
            log.warning("Shutdown called")
            await ctx.send("Shutting down 🌙")
            await self.bot.close()

    @commands.command(name="setname", brief="Renames the bot")
    async def cmdSetName(self, ctx: commands.Context, name: str):
        if await self.bot.is_owner(ctx.author):
            await self.bot.user.edit(username=name)

    @commands.command(name="setAvatar", brief="Sets the bots avatar")
    async def cmdSetAvatar(self, ctx: commands.Context):
        if await self.bot.is_owner(ctx.author):
            if ctx.message.attachments:
                photo = ctx.message.attachments[0].url
                async with aiohttp.ClientSession() as session:
                    async with session.get(photo) as r:
                        if r.status == 200:
                            data = await r.read()
                            try:
                                await self.bot.user.edit(avatar=data)
                                return await ctx.send("Set avatar, how do i look?")
                            except discord.HTTPException:
                                await ctx.send("Unable to set avatar")
                                return
            await ctx.send("I cant read that")

    def get_syntax_error(self, e):
        if e.text is None:
            return '```py\n{0.__class__.__name__}: {0}\n```'.format(e)
        return '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)

    @commands.command(name="exec", brief="Execute some code")
    @commands.is_owner()
    async def _exec(self, ctx: commands.Context, *, body: str):
        env = {
            'bot': self.bot,
            'slash': self.bot.slash,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'server': ctx.guild,
            'guild': ctx.guild,
            'message': ctx.message
        }
        env.update(globals())

        if body.startswith('```') and body.endswith('```'):
            body = '\n'.join(body.split('\n')[1:-1])
        else:
            body = body.strip('` \n')

        stdout = io.StringIO()

        to_compile = 'async def func():\n%s' % textwrap.indent(body, '  ')

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env['func']
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send('```py\n{}{}\n```'.format(value, traceback.format_exc()))
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except:
                pass

            if ret is None:
                if value:
                    await ctx.send('```py\n%s\n```' % value)
            else:
                self._last_result = ret
                await ctx.send('```py\n%s%s\n```' % (value, ret))

    @commands.command(name="status", brief="Status of the bot")
    async def cmdStatus(self, ctx: commands.Context):
        if await self.bot.is_owner(ctx.author):
            # grab DB data
            setupGuilds = len(await self.bot.db.execute('SELECT * FROM QOTDBot.guilds WHERE timeZone IS NOT NULL'))
            totalQuestions = await self.bot.db.execute(
                "SELECT COUNT(*) FROM QOTDBot.questions ", getOne=True
            )
            totalLog = await self.bot.db.execute(
                "SELECT COUNT(*) FROM QOTDBot.questionLog ", getOne=True
            )

            # get qotd cog's data
            scheduledTasks = "Error, could not determine"
            cog = self.bot.get_cog("QOTD")
            if hasattr(cog, "scheduler"):
                scheduledTasks = len(cog.scheduler.get_jobs())

            # get uptime and human format it
            uptime = datetime.now() - self.bot.startTime
            days, remainder = divmod(uptime.total_seconds(), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)

            if days != 0:
                days = f"{days} day{'s' if days > 1 else ''}, "
            else:
                days = ""

            message = [
                "```css",
                f"Logged in as       : '{self.bot.user.name} #{self.bot.user.discriminator}'",
                f"User ID            : '{self.bot.user.id}'",
                f"Start Time         : '{self.bot.startTime.ctime()}'",
                f"Uptime             : '{days}{round(hours):02}:{round(minutes):02}:{round(seconds):02}'",
                f"DB Connection Type : '{'Tunneled' if self.bot.db.tunnel else 'Direct'}'",
                f"DB Operations      : '{self.bot.db.operations}'",
                f"Stored Questions   : '{totalQuestions['COUNT(*)']}'",
                f"Question Log Size  : '{totalLog['COUNT(*)']}'",
                f"Scheduled Tasks    : '{scheduledTasks}'",
                f"Server Count       : '{len(self.bot.guilds)}'",
                f"Setup Servers      : '{setupGuilds}'",
                f"Cog Count          : '{len(self.bot.cogs)}'",
                f"Command Count      : '{len(self.slash.commands)}'",
                f"Discord.py Version : '{discord.__version__}'",
                "```"
            ]
            message.insert(1, "BOT INFO".center(len(max(message, key=len)), "-"))
            message.insert(len(message) - 1, "END BOT INFO".center(len(max(message, key=len)), "-"))
            await ctx.send("\n".join(message))


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Base(bot))
    log.info("Base mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Base un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
