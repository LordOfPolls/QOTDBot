import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

import discord
import discord_slash.error
from discord.ext import commands, tasks
from discord_slash import cog_ext, SlashContext

from source import utilities, checks, jsonManager

log = utilities.getLog("Cog::polls", level=9)


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        strEmoji = "0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 🇦 🇧 🇨 🇩 🇪 🇫 🇬 🇭"
        self.emoji = strEmoji.split(" ")
        self.booleanEmoji = ["✅", "❎"]
        self.bothEmoji = self.emoji + self.booleanEmoji
        self.pollsToUpdate = set()
        self.bot.add_listener(self.reactionProcessor, "on_raw_reaction_add")
        self.bot.add_listener(self.reactionProcessor, "on_raw_reaction_remove")

    async def setup(self):
        log.info("Starting poll tasks...")
        self.updatePoll.start()
        self.closePollsTask.start()

    async def createProgBars(self, message: discord.Message, embed: discord.Embed, pollData: dict):
        """Creates a series of progress bars to represent poll options"""

        # total all reactions that are part of the poll
        options = json.loads(pollData['options'])
        totalReactions = 0

        for reaction in message.reactions:
            try:
                if reaction.emoji in str(options):
                    totalReactions += reaction.count - 1
            except TypeError:
                continue

        for reaction in message.reactions:
            try:
                if reaction.emoji in str(options):
                    # create a progress bar for this emoji
                    progBarStr = ''
                    progBarLength = 10
                    percentage = 0
                    if totalReactions != 0:
                        percentage = (reaction.count - 1) / totalReactions
                        for i in range(progBarLength):
                            if round(percentage, 1) <= 1 / progBarLength * i:
                                progBarStr += u"░"
                            else:
                                progBarStr += u'▓'
                    else:
                        progBarStr = u"░" * progBarLength

                    # format and add progressbar to embed
                    progBarStr = progBarStr + f" {round(percentage * 100)}%"
                    name = [item for item in options if item.startswith(reaction.emoji)][0]
                    embed.add_field(name=name, value=progBarStr, inline=False)
            except TypeError:
                continue
        return embed

    @tasks.loop(seconds=30)
    async def closePollsTask(self):
        """Checks the stored polls to see if they should be closed"""
        log.spam("Checking poll end times...")
        pollData = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.polls WHERE endTime is not null",
        )
        for poll in pollData:
            endTime: datetime = poll['endTime']
            if endTime < datetime.now():
                log.spam(f"Poll needs closing: {poll['messageID']}")
                channel = self.bot.get_channel(int(poll['channelID']))
                message = await self.bot.getMessage(channel=channel, messageID=int(poll['messageID']))
                await self.closePoll(message)

    async def closePoll(self, message: discord.Message):
        """Closes the passed poll"""
        pollData = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.polls WHERE messageID = '{message.id}'",
            getOne=True
        )
        await self.bot.db.execute(
            f"DELETE FROM QOTDBot.polls WHERE messageID = '{message.id}'")
        if pollData is not None:
            log.info(f"Closing poll {message.id}")
            originalEmbed = message.embeds[0]
            embed = discord.Embed(
                title=f"Closed Poll",
                colour=discord.Colour(0x727272))

            if pollData['title']:
                embed.title += f"- {pollData['title']}"

            footerText = originalEmbed.footer.text
            embed.set_footer(text=footerText.split("•")[0])

            embed = await self.createProgBars(message, embed, pollData)

            await message.edit(embed=embed)

    async def createAndPostPoll(self, ctx: SlashContext, options: list, **kwargs):
        """Creates a poll with the passed kwargs, and posts it"""
        try:
            embed = utilities.defaultEmbed(title="Poll")
            title = None
            singleVote = None
            channel = None
            time = None
            timeData = None
            timeText = None
            singleText = None

            if "title" in kwargs and kwargs['title'] is not None:
                title = kwargs['title']
                embed.title = f"Poll - {title}"
            if "singleVote" in kwargs and kwargs['singleVote'] is not None:
                singleVote = True if kwargs['singleVote'] == "True" else False
            if "time" in kwargs and kwargs['time'] is not None:
                time = kwargs['time']
            if "channel" in kwargs and kwargs['channel'] is not None:
                channel = kwargs['channel']

            # sanity check options
            if len(options) > len(self.emoji):
                return await ctx.send(f"Sorry I can only support {len(self.emoji)} options :slight_frown: ")
            if time is not None and time <= 0:
                return await ctx.send("Sorry I cant do things in the past, please use a positive time value")

            # Process time
            if time is not None:
                timeData = datetime.now() + timedelta(minutes=time)
                # format time in human readable format
                days, remainder = divmod(time, 1440)
                hours, minutes = divmod(remainder, 60)

                days = "" if days == 0 else f"{days} day{'s' if days > 1 else ''} "
                hours = "" if hours == 0 else f"{hours} hour{'s' if hours > 1 else ''} "
                minutes = "" if minutes == 0 else f"{minutes} minute{'s' if minutes > 1 else ''} "
                timeText = f"• Closes after {days}{hours}{minutes}"

            singleText = "" if singleVote is False else "• Only 1 response per user "

            embed.set_footer(icon_url=ctx.author.avatar_url,
                             text=f"Asked by {ctx.author.display_name} {singleText}{timeText}")

            # pick emoji list to use
            if len(options) == 2:
                # if theres only 2 options, ticks and crosses look nicer
                emojiList = self.booleanEmoji
            else:
                emojiList = self.emoji
            # add options to embed
            for i in range(len(options)):
                options[i] = f"{emojiList[i]}- {options[i]}"
                embed.add_field(name=options[i], value="░░░░░░░░░░ 0%", inline=False)

            # send poll
            if channel:
                if not await utilities.checkPermsInChannel(ctx.guild.get_member(user_id=self.bot.user.id), channel):
                    return await ctx.send("Sorry, I am missing permissions in that channel.\n"
                                          "I need send messages, add reactions, manage messages, and embed links")
                msg = await channel.send(embed=embed)
            else:
                msg = await ctx.send(embed=embed)

            # add reactions to vote with
            await ctx.send("To close the poll, react to it with 🔴", hidden=True)
            for i in range(len(options)):
                await msg.add_reaction(emojiList[i])

            # post to DB
            options = await self.bot.db.escape(json.dumps(options))

            title = f"'{title}'" if title is not None else "null"
            timeData = f"'{timeData}'" if timeData is not None else "null"

            operation = (
                "INSERT INTO QOTDBot.polls (title, options, messageID, channelID, guildID, authorID, singleVote, endTime) "
                f"VALUES ({title}, '{options}', '{msg.id}', '{msg.channel.id}', '{ctx.guild.id}', '{ctx.author.id}', "
                f"{singleVote}, {timeData})"
            )

            await self.bot.db.execute(operation)
        except Exception as e:
            log.error(e)
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fileName = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(f"PollCreation error: {exc_type, fileName, exc_tb.tb_lineno}")

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("poll"))
    async def poll(self, ctx: SlashContext, options: str, title: str = None, channel=None, singlevote: str = "False",
                   time=None):
        """Creates a poll with custom options"""
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()

        if len(options) >= 2000:
            return await ctx.send("Sorry, but this would exceed discords character limit :slight_frown: ")
        options = options.split(", ")
        await self.createAndPostPoll(ctx,
                                     options=options,
                                     title=title,
                                     channel=channel,
                                     singleVote=singlevote,
                                     time=time)

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("pollgen.week"))
    async def pollGenWeek(self, ctx: SlashContext, title: str = None, channel=None, singlevote: str = "False",
                          time=None):
        """Creates a poll with day of week options"""
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.respond()
        options = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday"
        ]
        await self.createAndPostPoll(ctx,
                                     options=options,
                                     title=title,
                                     channel=channel,
                                     singleVote=singlevote,
                                     time=time)

    @tasks.loop(seconds=3)
    async def updatePoll(self):
        """Update the bars on polls
        We dont want to do this every time a reaction is added as we're gunna get rate limited almost constantly
        3 seconds is the maximum amount of time a user will consider fast, so every 3 seconds we update"""
        try:
            if len(self.pollsToUpdate) != 0:
                for item in self.pollsToUpdate.copy():
                    # pop out the item when we update, so we dont re-check it in 3 seconds for no reason
                    self.pollsToUpdate.remove(item)
                    channel: discord.TextChannel = self.bot.get_channel(int(item[1]))
                    if channel:
                        message: discord.Message = await self.bot.getMessage(messageID=int(item[0]), channel=channel)
                        if message:
                            originalEmbed = message.embeds[0]
                            embed = utilities.defaultEmbed(title=originalEmbed.title)
                            embed.set_footer(text=originalEmbed.footer.text, icon_url=originalEmbed.footer.icon_url)
                            # update fields
                            pollData = await self.bot.db.execute(
                                f"SELECT * FROM QOTDBot.polls WHERE messageID = '{message.id}'",
                                getOne=True
                            )
                            log.spam("Creating progbars")
                            embed = await self.createProgBars(message, embed, pollData)

                            if embed != originalEmbed:
                                log.spam("Updating poll")
                                return asyncio.ensure_future(message.edit(
                                    embed=embed, allowed_mentions=discord.AllowedMentions.none()
                                ))
                            else:
                                log.spam("No need to update")
        except Exception as e:
            log.error(e)

    async def reactionProcessor(self, payload: discord.RawReactionActionEvent):
        """Processing the reaction event to determine if a poll needs updating
        """
        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)
        message: discord.Message = await self.bot.getMessage(messageID=payload.message_id, channel=channel)
        if payload.user_id == self.bot.user.id:
            return

        if message:
            if message.author == self.bot.user and \
                    message.embeds and \
                    "Poll" in message.embeds[0].title:

                if payload.event_type == "REACTION_ADD":
                    if "🔴" == payload.emoji.name:
                        # checks if user is trying to close poll, and that user is the author
                        pollData = await self.bot.db.execute(
                            f"SELECT authorID FROM QOTDBot.polls WHERE messageID = '{message.id}'",
                            getOne=True
                        )
                        try:
                            if payload.user_id == int(pollData['authorID']):
                                return await self.closePoll(message)
                            else:
                                return asyncio.ensure_future(message.clear_reaction("🔴"))
                        except TypeError:
                            # this will be none if the author deleted their reaction before the poll could be closed
                            return

                    if str(message.embeds[0].colour) != "#727272":
                        # is the poll still open?
                        if "1 response" in message.embeds[0].footer.text:
                            # handles single response polls
                            user = self.bot.get_user(payload.user_id)
                            for reaction in message.reactions:
                                if reaction.emoji != payload.emoji.name:
                                    users = await reaction.users().flatten()
                                    if user.id in [u.id for u in users]:
                                        asyncio.ensure_future(reaction.remove(user=user))
                # add this message to a set to bulk update shortly
                if payload.emoji.name in self.emoji + self.booleanEmoji:
                    self.pollsToUpdate.add((payload.message_id, payload.channel_id))
                    log.spam("Submitted poll to update task")


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Polls(bot))
    log.info("Polls mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Polls un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
