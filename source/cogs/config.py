import re
from collections import Counter
from datetime import datetime
import discord
import discord_slash
import pytz
from discord.ext import commands
from discord_slash import cog_ext, SlashContext, error
from fuzzywuzzy import fuzz

from source import utilities, dataclass, checks, jsonManager

log = utilities.getLog("Cog::config")


class Config(commands.Cog):
    """Configuration options"""

    def __init__(self, bot: dataclass.Bot):
        self.bot = bot

        self.emoji = "⚙"

    async def submitToQOTD(self, guild: discord.Guild):
        """Tries to reschedule/create a job in QOTD for this guild"""
        for _cog in self.bot.cogs:
            if _cog == "QOTD":
                await self.bot.cogs[_cog].rescheduleTask(guildID=guild.id)
                return

    async def findMatchingTimezone(self, userInput: str):
        """Uses fuzzywuzzy to find a timezone matching the text passed"""
        matches = {}
        userInput = " ".join(userInput.split("/")).lower()
        for tz in pytz.all_timezones:
            _tz = " ".join(tz.split("/")).lower()
            fuzzResult = fuzz.partial_ratio(userInput, _tz)
            matches[tz] = fuzzResult

        mostSimilar = Counter(matches)
        return mostSimilar.most_common(1)[0][0]

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("setup.simple"))
    async def setupSimple(self, ctx: SlashContext):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()

        _emb = utilities.defaultEmbed(title="Simple Setup")

        # region: QOTDChannel
        embed = _emb.copy()
        embed.set_footer(text="Step 1/3")

        embed.description = \
            f"🔍**What channel do you want questions to be posted in?**🔍\n" \
            f"Please mention the channel\n\n" \
            f"Example: \"{ctx.channel.mention}\""
        msg = await ctx.send(embed=embed)

        # wait for user to set a channel
        result = await utilities.waitForChannelMention(ctx, msg)
        if result:
            if not await utilities.checkPermsInChannel(ctx.guild.get_member(user_id=self.bot.user.id), result):
                await ctx.send("Sorry, I am missing permissions in that channel.\n"
                               "I need send messages, add reactions, manage messages, and embed links\n")
                embed.colour = discord.Colour.red()
                embed.description = f"Setup Failed, use `/setup simple` to try again"
                await msg.edit(embed=embed)
            await self.bot.db.execute(
                f"UPDATE QOTDBot.guilds SET qotdChannel='{result.id}' "
                f"WHERE guildID = '{ctx.guild.id}'")
            embed.colour = discord.Colour.green()
            embed.description = f"Set QOTD Channel to {result.mention}"
            await msg.edit(embed=embed)
        else:
            embed.colour = discord.Colour.red()
            embed.description = f"Setup Failed, use `/setup simple` to try again"
            return await msg.edit(embed=embed)
        # endregion: QOTDChannel

        # region: Time zone
        embed = _emb.copy()
        embed.set_footer(text="Step 2/3")
        embed.description = \
            "🌍**Please tell me what time zone your server is in**🌏\n" \
            "A map of time zones can be found [here](https://kevinnovak.github.io/Time-Zone-Picker/)\n" \
            "**Note:** Please do not use abbreviations like EST, UTC, or GMT. Instead use the full format, " \
            "i.e. **<region>/<city>**\n\n" \
            "**Examples:**\n" \
            "Europe/London\n" \
            "America/New_York\n" \
            "Australia/Sydney"
        msg = await ctx.send(embed=embed)
        result = await utilities.waitForMessageFromAuthor(ctx)
        if result:
            await msg.delete()
            # try and find matching timezone
            possibleTimezone = await self.findMatchingTimezone(result.content)
            time = datetime.now(tz=pytz.timezone(possibleTimezone))
            embed.description = f"Setting your timezone to **{possibleTimezone}**\n" \
                                f"That would make it **{time.hour:02}:{time.minute:02}** for you?\n\n" \
                                f"React with 👍 if that's correct"
            msg = await ctx.send(embed=embed)
            result = await utilities.YesOrNoReactionCheck(ctx, msg)
            if result:
                # if it is correct, push to db, and return
                await self.bot.db.execute(
                    f"UPDATE QOTDBot.guilds SET timeZone='{possibleTimezone}' "
                    f"WHERE guildID = '{ctx.guild.id}'")
                embed.colour = discord.Colour.green()
                embed.description = f"Your timezone has been set to **{possibleTimezone}**"
                await msg.edit(embed=embed)
            else:
                embed.colour = discord.Colour.red()
                embed.description = f"Setup Failed, use `/setup simple` to try again"
                return await msg.edit(embed=embed)
        else:
            embed.colour = discord.Colour.red()
            embed.description = f"Setup Failed, use `/setup simple` to try again"
            return await msg.edit(embed=embed)
        # endregion: Time zone

        # region: time
        embed = _emb.copy()
        embed.set_footer(text="Step 2/3")
        embed.description = \
            f"🕖**At what time would you like questions to be asked?**🕖\n" \
            f"Please enter the hour of the day you'd like to get a question\n\n" \
            f"This should be a number from 0 to 23, as per the 24-hour clock.\n\n" \
            f"**Example:** 7"
        msg = await ctx.send(embed=embed)
        result = await utilities.waitForMessageFromAuthor(ctx)
        if result:
            hour = int(re.search(r'\d+', result.content).group())
            if 0 <= hour <= 23:
                # valid time
                await self.bot.db.execute(
                    f"UPDATE QOTDBot.guilds SET sendTime={hour} "
                    f"WHERE guildID = '{ctx.guild.id}'")
                _emb.colour = discord.Colour.green()
                _emb.description = f"Your questions will be sent at **{hour:02}:00**"
                await msg.edit(embed=_emb)
            else:
                await ctx.send("Sorry, the time has to be between 0 and 23")
                embed.colour = discord.Colour.red()
                embed.description = f"Setup Failed, use `/setup simple` to try again"
                return await msg.edit(embed=embed)
        else:
            await ctx.send("Sorry, the time has to be between 0 and 23")
            embed.colour = discord.Colour.red()
            embed.description = f"Setup Failed, use `/setup simple` to try again"
            return await msg.edit(embed=embed)
        # endregion: time

        await self.bot.db.execute(
            f"UPDATE QOTDBot.guilds SET enabled=TRUE "
            f"WHERE guildID = '{ctx.guild.id}'")

        _emb.colour = discord.Colour.gold()
        _emb.title = "🎉🥳🎉 **Setup Complete** 🎉🥳🎉"
        _emb.description = "QOTD has been configured and enabled. Enjoy :slight_smile:"
        await ctx.send(embed=_emb)

        await self.submitToQOTD(ctx.guild)

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
            f"UPDATE QOTDBot.guilds SET pinMessage = {option} WHERE guildID = '{ctx.guild.id}'")


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Config(bot))
    log.info("Config mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Config un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
