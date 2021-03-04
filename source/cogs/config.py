import re
from collections import Counter
from datetime import datetime

import discord
import discord_slash
import discord_slash.error
import pytz
from discord.ext import commands
from discord_slash import cog_ext, SlashContext
from discord_slash.utils import manage_commands
from fuzzywuzzy import fuzz

from source import utilities, dataclass, checks, jsonManager

log = utilities.getLog("Cog::config")


class Config(commands.Cog):
    """Configuration commands"""

    def __init__(self, bot: dataclass.Bot):
        self.bot = bot

        self.emoji = "⚙"

    def cog_check(self, ctx: commands.Context):
        if ctx.guild:
            if ctx.author.permissions_in(ctx.channel).manage_guild:
                return True

    async def submitToQOTD(self, guild: discord.Guild):
        """Tries to reschedule/create a job in qotd for this guild"""
        for _cog in self.bot.cogs:
            if _cog == "QOTD":
                await self.bot.cogs[_cog].rescheduleTask(guildID=guild.id)
                return

    # region options
    async def getQotdChannel(self, ctx: commands.Context, _emb: discord.Embed, step: tuple = None) -> bool:
        """Asks what channel to send to"""
        _emb.description = \
            f"🔍**What channel do you want questions to be posted in?**🔍\n" \
            f"Please mention the channel\n\n" \
            f"Example: \"{ctx.channel.mention}\""
        if step:
            _emb.set_footer(text=f"Step {step[0]}/{step[1]}")
        msg = await ctx.send(embed=_emb)
        result = await utilities.waitForChannelMention(ctx, msg)
        if result:
            if not await utilities.checkPermsInChannel(ctx.guild.get_member(user_id=self.bot.user.id), result):
                await ctx.send("Sorry, I am missing permissions in that channel.\n"
                               "I need send messages, add reactions, manage messages, and embed links")
                return False
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET qotdChannel='{result.id}' "
                f"WHERE guildID = '{ctx.guild.id}'")
            _emb.colour = discord.Colour.green()
            _emb.description = f"Set QOTD Channel to {result.mention}"
            await msg.edit(embed=_emb)
            return True
        else:
            return False

    async def getTimeZone(self, ctx: commands.Context, _emb: discord.Embed, step: tuple = None) -> bool:
        """Asks for the users timezone"""
        _emb.description = \
            "🌍**Please tell me what time zone your server is in**🌏\n" \
            "A map of time zones can be found [here](https://kevinnovak.github.io/Time-Zone-Picker/)\n" \
            "**Note:** Please do not use abbreviations like EST, UTC, or GMT. Instead use the full format, " \
            "i.e. **<region>/<city>**\n\n" \
            "**Examples:**\n" \
            "Europe/London\n" \
            "America/New_York\n" \
            "Australia/Sydney"
        if step:
            _emb.set_footer(text=f"Step {step[0]}/{step[1]}")
        msg = await ctx.send(embed=_emb)
        result = await utilities.waitForMessageFromAuthor(ctx)
        if result:
            await msg.delete()
            # try and find a matching timezone
            matches = {}
            userInput = result.content.lower()
            userInput = " ".join(userInput.split("/"))
            for tz in pytz.all_timezones:
                _tz = " ".join(tz.split("/")).lower()
                fuzzResult = fuzz.partial_ratio(userInput, _tz)
                matches[tz] = fuzzResult

            mostSimilar = Counter(matches)
            mostSimilar = mostSimilar.most_common(1)[0]

            # check with the user to see if this is correct
            time = datetime.now(tz=pytz.timezone(mostSimilar[0]))
            _resultEmb = _emb.copy()
            _emb.description = f"Setting your timezone to **{mostSimilar[0]}**\n" \
                               f"That would make it **{time.hour:02}:{time.minute:02}** for you?\n\n" \
                               f"React with 👍 if that's correct"
            msg = await ctx.send(embed=_emb)
            result = await utilities.YesOrNoReactionCheck(ctx, msg)
            if result:
                # if it is correct, upload to db, and return
                await self.bot.db.execute(
                    f"UPDATE QOTDBot.guilds SET timeZone='{mostSimilar[0]}' "
                    f"WHERE guildID = '{ctx.guild.id}'")
                _emb.colour = discord.Colour.green()
                _emb.description = f"Your timezone has been set to **{mostSimilar[0]}**"
                await msg.edit(embed=_emb)
                return True
            else:
                _emb.colour = discord.Colour.orange()
                _emb.description = "Oh okay, lets try again"
        return False

    async def getTime(self, ctx: commands.Context, _emb: discord.Embed, step: tuple = None) -> bool:
        """Asks what time the question should be posted at"""
        _emb.description = \
            f"🕖**At what time would you like questions to be asked?**🕖\n" \
            f"Please enter the hour of the day you'd like to get a question\n\n" \
            f"This should be a number from 0 to 23, as per the 24-hour clock.\n\n" \
            f"**Example:** 7"
        if step:
            _emb.set_footer(text=f"Step {step[0]}/{step[1]}")
        msg = await ctx.send(embed=_emb)
        hour = -1
        for i in range(3):
            # will allow for 3 invalid messages before giving up
            result = await utilities.waitForMessageFromAuthor(ctx)
            try:
                # users can be weird and not just give the number, this strips all non digits
                hour = int(re.search(r'\d+', result.content).group())
                if 0 <= hour <= 23:
                    # valid time
                    break
                else:
                    # invalid time
                    continue
            except AttributeError:
                continue
        else:
            # user didnt give a valid response in time
            return False
        await self.bot.db.execute(
            f"UPDATE QOTDBot.guilds SET sendTime={hour} "
            f"WHERE guildID = '{ctx.guild.id}'")
        _emb.colour = discord.Colour.green()
        _emb.description = f"Your questions will be sent at **{hour:02}:00**"
        await msg.edit(embed=_emb)
        return True

    # endregion options

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.active"))
    async def slashActive(self, ctx, state: str = "False"):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        state = True if state == "True" else False
        if state:
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET enabled=TRUE "
                f"WHERE guildID = '{ctx.guild.id}'")
            await ctx.send("QOTD has been enabled")
            log.debug(f"{ctx.guild.id} enabled QOTD")
        else:
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET enabled=FALSE "
                f"WHERE guildID = '{ctx.guild.id}'")
            await ctx.send("QOTD has been disabled")
            log.debug(f"{ctx.guild.id} disabled QOTD")

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.simple"))
    async def slashSetup(self, ctx: SlashContext):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        _emb = utilities.defaultEmbed(title="Simple Setup")
        step = 1

        if not await self.getQotdChannel(ctx, _emb.copy(), (step, 3)):
            return await ctx.send("Setup aborted")
        step += 1

        if not await self.getTimeZone(ctx, _emb.copy(), (step, 3)):
            return await ctx.send("Setup aborted")
        step += 1

        if not await self.getTime(ctx, _emb.copy(), (step, 3)):
            return await ctx.send("Setup aborted")
        step += 1

        await self.bot.db.execute(
            f"UPDATE QOTDBot.guilds SET enabled=TRUE "
            f"WHERE guildID = '{ctx.guild.id}'")

        _emb.colour = discord.Colour.gold()
        _emb.title = "🎉🥳🎉 **Setup Complete** 🎉🥳🎉"
        await ctx.send(embed=_emb)

        await self.submitToQOTD(ctx.guild)

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.time"))
    async def slashSetTime(self, ctx: SlashContext, hour: int):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        if hour == 24:
            hour = 0
        if hour > 24 or hour < 0:
            return await ctx.send("Only hours 0-24 are accepted")

        await self.bot.db.execute(
            f"UPDATE QOTDBot.guilds SET sendTime={hour} "
            f"WHERE guildID = '{ctx.guild.id}'")
        _emb = utilities.defaultEmbed(title="Set Time", colour=discord.Colour.green())
        _emb.description = f"Your questions will be sent at **{hour:02}:00**"
        await ctx.send(embed=_emb)
        await self.submitToQOTD(ctx.guild)

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.timezone"))
    async def slashSetTimeZone(self, ctx: SlashContext, timezone: str):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        # try and find a matching timezone
        matches = {}
        userInput = timezone.lower()
        userInput = " ".join(userInput.split("/"))
        for tz in pytz.all_timezones:
            _tz = " ".join(tz.split("/")).lower()
            fuzzResult = fuzz.partial_ratio(userInput, _tz)
            matches[tz] = fuzzResult

        mostSimilar = Counter(matches)
        mostSimilar = mostSimilar.most_common(1)[0]
        if mostSimilar[1] < 70:
            return await ctx.send(
                "Sorry, I couldn't recognise that timezone. Use [this website](https://kevinnovak.github.io/Time-Zone-Picker/) to get a timezone i'll understand :smile:")

        # check with the user to see if this is correct
        time = datetime.now(tz=pytz.timezone(mostSimilar[0]))
        _emb = utilities.defaultEmbed(title="Set Timezone")
        _emb.description = f"Setting your timezone to **{mostSimilar[0]}**\n" \
                           f"That would make it **{time.hour:02}:{time.minute:02}** for you?\n\n" \
                           f"React with 👍 if that's correct"
        msg = await ctx.send(embed=_emb)
        result = await utilities.YesOrNoReactionCheck(ctx, msg)
        if result:
            # if it is correct, upload to db, and return
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET timeZone='{mostSimilar[0]}' "
                f"WHERE guildID = '{ctx.guild.id}'")
            _emb.colour = discord.Colour.green()
            _emb.description = f"Your timezone has been set to **{mostSimilar[0]}**"
            await msg.edit(embed=_emb)
            await self.submitToQOTD(ctx.guild)
            return True
        else:
            _emb.colour = discord.Colour.orange()
            _emb.description = "Oh okay, if you want to try again, type the command again"
            await ctx.send(embed=_emb)

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.channel"))
    async def slashSetChannel(self, ctx: SlashContext,
                              channel: discord.TextChannel or discord.CategoryChannel or discord.VoiceChannel):
        """Sets the channel to ask questions"""
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        _emb = utilities.defaultEmbed(title="Set QOTD Channel")
        if isinstance(channel, discord.TextChannel):
            if not await utilities.checkPermsInChannel(ctx.guild.get_member(user_id=self.bot.user.id), channel):
                return await ctx.send("Sorry, I am missing permissions in that channel.\n"
                                      "I need send messages, add reactions, manage messages, and embed links")
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET qotdChannel='{channel.id}' "
                f"WHERE guildID = '{ctx.guild.id}'")
            _emb.colour = discord.Colour.green()
            _emb.description = f"Set QOTD Channel to {channel.mention}"
            await ctx.send(embed=_emb)
            return True
        else:
            _emb.colour = discord.Colour.orange()
            _emb.description = "Sorry thats not a valid text channel :confused:"
            await ctx.send(embed=_emb)

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.role"))
    async def slashSetMention(self, ctx, role: discord.Role or None = None, clear: str = None):
        """Sets a role that will be mentioned when a question is posted """
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        if isinstance(role, str) and clear is None:
            clear = role
            role = None

        if role is None and clear is None:
            return await ctx.send("Please choose an option that appears in the commands list")
        clear = True if clear == "True" else False

        if not clear:
            if isinstance(role, discord.Role):
                if role.mentionable:
                    await self.bot.db.execute(
                        f"UPDATE QOTDBot.guilds SET mentionRole = '{role.id}' WHERE guildID = '{ctx.guild.id}'"
                    )
                    return await ctx.send(f"Got it, i'll mention {role.mention} whenever a QOTD is posted",
                                          allowed_mentions=discord.AllowedMentions.none())
                else:
                    return await ctx.send(f"{role.name} is not mentionable, please check your role settings")
            else:
                return ctx.send("You did not choose a role to mention")
        else:
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET mentionRole = NULL WHERE guildID = '{ctx.guild.id}'"
            )
            return await ctx.send("Got it, i wont mention anybody when i post")

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.pin"))
    async def slashSetPin(self, ctx, option: str = "False"):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        option = True if option == "True" else False
        if option:
            await ctx.send("Okay, I'll pin questions from now on 📌")
        else:
            await ctx.send("Okay, no pinning")
        await self.bot.db.execute(
            f"UPDATE QOTDBot.guilds SET pinMessage = {option} WHERE guildID = '{ctx.guild.id}'"
        )


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Config(bot))
    log.info("Config mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Config un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
