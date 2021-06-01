import asyncio
import json
import os
import sys
import typing
from datetime import datetime, timedelta

import redis
import jsonpickle
import discord
import discord_slash.error
from discord.ext import commands, tasks
from discord_slash import cog_ext, SlashContext, ComponentContext
from discord_slash.utils import manage_components, manage_commands

from source import utilities, checks, jsonManager

log = utilities.getLog("Cog::polls")


class PollData:
    """Represents a poll"""

    def __init__(
        self,
        author_id,
        title="",
        poll_options=None,
        expiry_time=None,
        single_vote=False,
    ):
        if poll_options is None:
            poll_options = []
        self.title = title
        self.options: typing.List[Option] = poll_options
        self.expiry_time: datetime = expiry_time
        self.single_vote: bool = single_vote

        self.channel_id: int = 0
        self.author_id: int = author_id
        self.message_id: int = 0


class Option:
    """Represents a poll option"""

    def __init__(self, option_text="Unset", emoji="❓"):
        super().__init__()
        self.text = option_text
        self.emoji = emoji
        self.voters: typing.List[int] = []
        self.style: int = 1


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        strEmoji = "1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 🇦 🇧 🇨 🇩 🇪 🇫 🇬 🇭"
        self.emoji = strEmoji.split(" ")
        self.booleanEmoji = ["✔", "✖"]
        self.bothEmoji = self.emoji + self.booleanEmoji
        self.pollsToUpdate = set()
        self.bot.add_listener(self.on_component, "on_component")
        self.bot.add_listener(self.reactionProcessor, "on_raw_reaction_add")
        self.polls = {}
        self.redis = redis.Redis(host="localhost", port=6379, db=1)

        # add pollGen commands
        prefab = jsonManager.getDecorator("pollPrefab")
        pWeek = prefab.copy()
        pBoolean = prefab.copy()
        pWeek["name"] = "week"
        pWeek["description"] = "Post a poll with all the days of the week"
        pBoolean["name"] = "boolean"
        pBoolean["description"] = "Post a poll with yes or no options"
        bot.slash.add_subcommand(cmd=self.pollPrefab, **pWeek)
        bot.slash.add_subcommand(cmd=self.pollPrefab, **pBoolean)

    async def setup(self):
        log.info("Starting poll tasks...")
        self.closePollsTask.start()
        try:
            self.redis.ping()
        except Exception as e:
            log.critical(e)
            exit(1)

    async def on_component(self, ctx: ComponentContext):
        await ctx.defer(edit_origin=True)

        poll: typing.Optional[PollData] = await self.get_poll(ctx.origin_message_id)
        if poll:
            old_embed = ctx.origin_message.embeds[0]
            new_embed = utilities.defaultEmbed(title=old_embed.title)
            new_embed.set_footer(
                text=old_embed.footer.text, icon_url=old_embed.footer.icon_url
            )
            option_id = int(ctx.custom_id.split("|")[-1])

            option: Option = poll.options[option_id]
            if ctx.author.id not in option.voters:
                option.voters.append(ctx.author.id)
            else:
                option.voters.remove(ctx.author.id)

            total_votes = 0
            for _option in poll.options:
                if poll.single_vote:
                    if _option != option:
                        if ctx.author.id in _option.voters:
                            _option.voters.remove(ctx.author.id)
                total_votes += len(_option.voters)

            for _option in poll.options:
                new_embed.add_field(
                    name=f"{_option.emoji} {_option.text}",
                    value=self.create_bar(len(_option.voters), total_votes),
                    inline=False,
                )
            await asyncio.to_thread(
                self.redis.set, ctx.origin_message_id, jsonpickle.encode(poll)
            )
            new_embed.description = f"{total_votes} vote{'s' if total_votes > 1 or total_votes == 0 else ''}"

            await ctx.edit_origin(embed=new_embed)

    def create_bar(self, count, total):
        progBarStr = ""
        progBarLength = 10
        percentage = 0
        if total != 0:
            percentage = count / total
            for i in range(progBarLength):
                if round(percentage, 1) <= 1 / progBarLength * i:
                    progBarStr += "░"
                else:
                    progBarStr += "▓"
        else:
            progBarStr = "░" * progBarLength
        progBarStr = progBarStr + f" {round(percentage * 100)}%"
        return progBarStr

    async def get_poll(self, message_id: int) -> PollData:
        try:
            raw_data = await asyncio.to_thread(self.redis.get, message_id)
            data = jsonpickle.decode(raw_data)
            if isinstance(data, PollData):
                return data

            poll = PollData(0)
            for key in data.keys():
                if hasattr(poll, key):
                    poll.__setattr__(key, data.get(key))
            return poll
        except Exception as e:
            log.error(e)
            return None

    @tasks.loop(seconds=30)
    async def closePollsTask(self):
        """Checks the stored polls to see if they should be closed"""
        log.spam("Checking poll end times...")
        keys = await asyncio.to_thread(self.redis.keys, "*")
        for key in keys:
            poll = await self.get_poll(key)
            if poll.expiry_time is not None:
                if poll.expiry_time < datetime.now():
                    log.spam(f"Poll needs closing: {poll.message_id}")

                    await self.close_poll(poll)

    async def close_poll(self, poll):
        channel = self.bot.get_channel(int(poll.channel_id))
        message = await self.bot.getMessage(
            channel=channel, messageID=int(poll.message_id)
        )
        if message:
            originalEmbed = message.embeds[0]
            embed = discord.Embed(title=f"Closed Poll", colour=discord.Colour(0x727272))

            if poll.title:
                embed.title += f"- {poll.title}"

            footerText = originalEmbed.footer.text
            embed.set_footer(text=footerText.split("•")[0])

            for field in originalEmbed.fields:
                embed.add_field(name=field.name, value=field.value, inline=False)

            embed.description = originalEmbed.description

            await message.edit(embed=embed, components=None)

            await asyncio.to_thread(self.redis.delete, poll.message_id)

    async def create_and_post_poll(self, ctx: SlashContext, options: list, **kwargs):
        """Create a poll with the passed kwargs and post it"""
        try:
            embed = utilities.defaultEmbed(title="Poll")
            temp_time = None
            poll_data = PollData(ctx.author_id)

            if "title" in kwargs and kwargs["title"] is not None:
                poll_data.title = kwargs.get("title")
                embed.title = f"Poll - {poll_data.title}"
            else:
                poll_data.title = f"From {ctx.author.display_name}"
                embed.title = f"Poll - {poll_data.title}"
            if "singlevote" in kwargs and kwargs["singlevote"] is not None:
                poll_data.single_vote = (
                    False if kwargs.get("singlevote") == "False" else True
                )
            if "time" in kwargs and kwargs["time"] is not None:
                temp_time = kwargs.get("time")
            if "channel" in kwargs and kwargs["channel"] is not None:
                poll_data.channel_id = kwargs.get("channel").id
            else:
                poll_data.channel_id = ctx.channel_id

            # sanity check options
            if len(options) > len(self.emoji):
                return await ctx.send(
                    f"Sorry I can only support {len(self.emoji)} options :slight_frown: "
                )
            if temp_time is not None and temp_time <= 0:
                return await ctx.send(
                    "Sorry I cant do things in the past, please use a positive time value"
                )

            # process time
            if temp_time is not None:
                poll_data.expiry_time = datetime.now() + timedelta(minutes=temp_time)
                # format time in human readable format
                days, remainder = divmod(temp_time, 1440)
                hours, minutes = divmod(remainder, 60)

                days = "" if days == 0 else f"{days} day{'s' if days > 1 else ''} "
                hours = "" if hours == 0 else f"{hours} hour{'s' if hours > 1 else ''} "
                minutes = (
                    ""
                    if minutes == 0
                    else f"{minutes} minute{'s' if minutes > 1 else ''} "
                )
                time_text = f"• Closes after {days}{hours}{minutes}"
            else:
                time_text = ""

            single_text = (
                "" if poll_data.single_vote is False else "• Only 1 response per user "
            )

            embed.set_footer(
                icon_url=ctx.author.avatar_url,
                text=f"Asked by {ctx.author.display_name} {single_text}{time_text}",
            )

            # pick an emoji list
            if len(options) == 2:
                emoji_list = self.booleanEmoji
            else:
                emoji_list = self.emoji

            # add options to embed and create buttons
            buttons = []
            for i in range(len(options)):
                _option = Option(option_text=options[i], emoji=emoji_list[i])
                options[i] = f"{_option.emoji}- {_option.text}"
                embed.add_field(
                    name=f"{_option.emoji} {_option.text}",
                    value="░░░░░░░░░░ 0%",
                    inline=False,
                )
                poll_data.options.append(_option)

                _option.style = 1  # blue, default
                if emoji_list == self.booleanEmoji:
                    # for boolean use red and green
                    _option.style = 4  # red
                    if i == 0:
                        _option.style = 3  # green

                buttons.append(
                    manage_components.create_button(
                        style=_option.style,
                        custom_id=f"poll|{ctx.guild_id}|{ctx.channel_id}|{i}",
                        emoji=_option.emoji,
                    )
                )

            # assemble action_rows
            action_row_buttons = []
            components = []
            for button in buttons:
                action_row_buttons.append(button)
                if len(action_row_buttons) == 5:
                    components.append(
                        manage_components.create_actionrow(*action_row_buttons)
                    )
                    action_row_buttons = []
            if len(action_row_buttons) != 0:
                components.append(
                    manage_components.create_actionrow(*action_row_buttons)
                )

            # post
            if channel := kwargs.get("channel"):
                if not await utilities.checkPermsInChannel(
                    ctx.guild.get_member(user_id=self.bot.user.id), channel
                ):
                    return await ctx.send(
                        "Sorry, I am missing permissions in that channel.\n"
                        "I need send messages, add reactions, manage messages, and embed links"
                    )
                msg = await channel.send(embed=embed, components=components)
            else:
                msg = await ctx.send(embed=embed, components=components)

            await ctx.send("To close the poll, react to it with 🔴", hidden=True)

            poll_data.message_id = msg.id
            await asyncio.to_thread(
                self.redis.set, msg.id, jsonpickle.encode(poll_data.__dict__)
            )
        except Exception as e:
            log.error(e)
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fileName = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(f"PollCreation error: {exc_type, fileName, exc_tb.tb_lineno}")

    @commands.check(checks.botHasPerms)
    @cog_ext.cog_slash(**jsonManager.getDecorator("poll"))
    async def poll(
        self,
        ctx: SlashContext,
        options: str,
        title: str = None,
        channel=None,
        singlevote: str = "False",
        time=None,
    ):
        """Creates a poll with custom options"""
        if not checks.botHasPerms(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()

        if len(options) >= 2000:
            return await ctx.send(
                "Sorry, but this would exceed discords character limit :slight_frown: "
            )
        options = options.split(", ")
        await self.create_and_post_poll(
            ctx,
            options=options,
            title=title,
            channel=channel,
            singleVote=singlevote,
            time=time,
        )

    @commands.check(checks.botHasPerms)
    async def pollPrefab(
        self,
        ctx: SlashContext,
        title: str = None,
        channel=None,
        singlevote: str = "False",
        time=None,
    ):
        """Creates a poll with preset options"""
        await ctx.defer()
        if ctx.subcommand_name == "week":
            options = [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ]
        elif ctx.subcommand_name == "boolean":
            options = ["Yes", "No"]
        else:
            return await ctx.send(
                "If you are seeing this, something has gone terribly wrong, "
                "please use `/server` and report it in my server"
            )
        await self.create_and_post_poll(
            ctx,
            options=options,
            title=title,
            channel=channel,
            singlevote=singlevote,
            time=time,
        )

    @cog_ext.cog_subcommand(
        base="poll_edit",
        name="add",
        description="Add an option to a poll",
        options=[
            manage_commands.create_option(
                name="message_id",
                description="The message id of the poll (hint, right click on it to get the ID",
                option_type=str,
                required=True,
            ),
            manage_commands.create_option(
                name="option_name",
                description="The new option you want to add",
                option_type=str,
                required=True,
            ),
        ],
    )
    async def poll_add_option(
        self, ctx: SlashContext, message_id: str, option_name: str
    ):
        """Add an option to an existing poll"""
        await ctx.defer()
        poll = await self.get_poll(int(message_id))
        if poll:
            message = await self.bot.getMessage(
                poll.message_id, self.bot.get_channel(poll.channel_id)
            )
            total_options = len(poll.options)
            if total_options >= len(self.emoji):
                return await ctx.send("Sorry that poll is full")
            poll.options.append(
                Option(option_text=option_name, emoji=self.emoji[total_options])
            )

            old_embed = message.embeds[0]
            new_embed = utilities.defaultEmbed(title=old_embed.title)
            new_embed.set_footer(
                text=old_embed.footer.text, icon_url=old_embed.footer.icon_url
            )
            total_votes = 0
            for _option in poll.options:
                total_votes += len(_option.voters)

            buttons = []
            for i in range(len(poll.options)):
                _option = poll.options[i]
                new_embed.add_field(
                    name=f"{_option.emoji} {_option.text}",
                    value=self.create_bar(len(_option.voters), total_votes),
                    inline=False,
                )
                buttons.append(
                    manage_components.create_button(
                        style=_option.style,
                        custom_id=f"poll|{ctx.guild_id}|{ctx.channel_id}|{i}",
                        emoji=_option.emoji,
                    )
                )
            await asyncio.to_thread(self.redis.set, message.id, jsonpickle.encode(poll))
            new_embed.description = f"{total_votes} vote{'s' if total_votes > 1 or total_votes == 0 else ''}"

            # assemble action_rows
            action_row_buttons = []
            components = []
            for button in buttons:
                action_row_buttons.append(button)
                if len(action_row_buttons) == 5:
                    components.append(
                        manage_components.create_actionrow(*action_row_buttons)
                    )
                    action_row_buttons = []
            if len(action_row_buttons) != 0:
                components.append(
                    manage_components.create_actionrow(*action_row_buttons)
                )

            await message.edit(embed=new_embed, components=components)
            await ctx.send(f"`{option_name}` was added to that poll")

        else:
            await ctx.send(
                "Sorry, I could not find that message, this support article might help: https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-"
            )

    async def reactionProcessor(self, payload: discord.RawReactionActionEvent):
        """Processing the reaction event to determine if a poll needs updating"""
        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)
        message: discord.Message = await self.bot.getMessage(
            messageID=payload.message_id, channel=channel
        )
        if payload.user_id == self.bot.user.id:
            return

        if message:
            if (
                message.author == self.bot.user
                and message.embeds
                and "Poll" in message.embeds[0].title
            ):

                if payload.event_type == "REACTION_ADD":
                    if "🔴" == payload.emoji.name:
                        # checks if user is trying to close poll, and that user is the author
                        poll = await self.get_poll(message.id)
                        try:
                            if payload.user_id == int(poll.author_id):
                                return await self.close_poll(poll)
                        except TypeError:
                            # this will be none if the author deleted their reaction before the poll could be closed
                            return


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Polls(bot))
    log.info("Polls mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning("Polls un-mounted")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
