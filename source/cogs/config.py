import re

import discord
from discord.ext import commands
from discord_slash import cog_ext, SlashContext
from discord_slash.utils import manage_commands
from source import utilities, dataclass
import pytz
from fuzzywuzzy import fuzz
from collections import Counter
from datetime import datetime

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
            f"🔍**Where do you want your questions to be posted?**\n" \
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
            f"🌍**Please tell me what timezone your server is in**\n" \
            f"This is used to send questions at the right time for you.\n\n" \
            f"A map of timezones can be found [here](https://kevinnovak.github.io/Time-Zone-Picker/)\n\n" \
            f"**Note:** Please do not use time zone abbreviations like EST, UTC, or GMT. " \
            f"Instead use this format: **<region>/<city>**\n\n" \
            f"**Examples:**\n" \
            f"Europe/London\n" \
            f"America/New_York\n" \
            f"Australia/Sydney"
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
            f"🕖**What time would you like to be asked?**\n" \
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

    @cog_ext.cog_subcommand(base="setup", name="active", description="Toggles if QOTDBot should be posting questions",
                            options=[
                                utilities.createBooleanOption(name="state", description="Should questions be posted",
                                                              required=True)
                            ])
    async def slashActive(self, ctx, state: str = "False"):
        await ctx.respond()
        if await utilities.slashCheck(ctx):
            if await utilities.checkGuildIsSetup(ctx):
                state = True if state == "True" else False
                if state:
                    await self.bot.db.execute(
                        f"UPDATE QOTDBot.guilds SET enabled=TRUE "
                        f"WHERE guildID = '{ctx.guild.id}'")
                    await ctx.send("QOTD has been enabled")
                else:
                    await self.bot.db.execute(
                        f"UPDATE QOTDBot.guilds SET enabled=FALSE "
                        f"WHERE guildID = '{ctx.guild.id}'")
                    await ctx.send("QOTD has been disabled")

    @cog_ext.cog_subcommand(base="setup", name="Simple", description="A simple setup to get the questions coming",
                            )
    async def slashSetup(self, ctx: SlashContext):
        await ctx.respond()
        if await utilities.slashCheck(ctx):

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

    @cog_ext.cog_subcommand(base="setup", name="Time", description="Sets the time for questions to be asked",
                            options=[
                                manage_commands.create_option(
                                    name="hour",
                                    description="An hour, in the 24 hour clock",
                                    option_type=int,
                                    required=True,
                                )
                            ])
    async def slashSetTime(self, ctx: SlashContext, hour: int):
        await ctx.respond()
        if await utilities.slashCheck(ctx):
            if await utilities.checkGuildIsSetup(ctx):
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

    @cog_ext.cog_subcommand(base="setup", name="TimeZone", description="Sets the timezone for your server",
                            options=[
                                manage_commands.create_option(
                                    name="timezone",
                                    description="your timezone",
                                    option_type=str,
                                    required=True,
                                )
                            ])
    async def slashSetTimeZone(self, ctx: SlashContext, timezone: str):
        await ctx.respond()
        if await utilities.slashCheck(ctx):
            if await utilities.checkGuildIsSetup(ctx):
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

    @cog_ext.cog_subcommand(base="setup", name="Channel", description="Sets the channel to ask questions",
                            options=[
                                manage_commands.create_option(
                                    name="channel",
                                    description="The channel you want QOTD sent in",
                                    option_type=7,
                                    required=True
                                )
                            ])
    async def slashSetChannel(self, ctx: SlashContext,
                              channel: discord.TextChannel or discord.CategoryChannel or discord.VoiceChannel):
        """Sets the channel to ask questions"""
        await ctx.respond()
        if await utilities.slashCheck(ctx):
            if await utilities.checkGuildIsSetup(ctx):
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


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Config(bot))
    log.info("Config mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Config un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
