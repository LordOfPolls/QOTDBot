from pprint import pprint

import discord
from discord.ext import commands, tasks
from source import utilities
import string
from discord_slash import cog_ext, SlashContext
from discord_slash.utils import manage_commands

log = utilities.getLog("Cog::polls")


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        strEmoji = "0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟 🇦 🇧 🇨 🇩 🇪 🇫 🇬 🇭 🇮"
        self.emoji = strEmoji.split(" ")
        self.booleanEmoji = ["✅", "❎"]
        self.pollsToUpdate = set()
        self.updatePoll.start()
        self.bot.add_listener(self.reactionProcessor, "on_raw_reaction_add")
        self.bot.add_listener(self.reactionProcessor, "on_raw_reaction_remove")

    def createBar(self, message: discord.Message, emoji):
        """Creates a progress bar based on the reaction distribution on a message"""
        totalReactions = sum([r.count - 1 for r in message.reactions])
        for reaction in message.reactions:
            if reaction.emoji == emoji:
                progBarStr = ''
                progBarLength = 10
                if totalReactions != 0:
                    percentage = (reaction.count - 1) / totalReactions
                    for i in range(progBarLength):
                        if percentage <= 1 / progBarLength * i:
                            progBarStr += u"░"
                        else:
                            progBarStr += u'▓'
                else:
                    progBarStr = u"░" * progBarLength
                return progBarStr

    @cog_ext.cog_slash(name="poll", description="Create a poll -- polls update every 3 seconds",
                       options=[
                           manage_commands.create_option(
                               name="options",
                               option_type=str,
                               description="The options of your poll, separated by commas",
                               required=True
                           ),
                           manage_commands.create_option(
                               name="title",
                               option_type=str,
                               description="Optional. A title for your poll",
                               required=False
                           ),
                           manage_commands.create_option(
                               name="channel",
                               option_type=7,
                               description="Optional. Send the poll to a different channel than this one",
                               required=False
                           ),
                           utilities.createBooleanOption("singlevote", description="Only allow one response per user")
                       ])
    async def poll(self, ctx: SlashContext, options: str, title: str = None, channel=None,
                   singlevote: str = "False"):
        """Create a poll in the current channel"""
        await ctx.respond()
        singleVote = True if singlevote == "True" else False

        # validate options
        if len(options) >= 2000:
            return await ctx.send("Sorry, but this would exceed discords character limit :sad:")
        options = options.split(", ")
        if len(options) > len(self.emoji):
            return await ctx.send(f"Sorry, for now I can only support {len(self.emoji)} options :sad:")

        extra = "" if singleVote is False else "• Only 1 response per user"
        embed = utilities.defaultEmbed(title="Poll" if title is None else f"Poll - {title}")
        embed.set_footer(icon_url=ctx.author.avatar_url, text=f"Asked by {ctx.author.display_name} {extra}")

        if len(options) == 2:
            emojiList = self.booleanEmoji
        else:
            emojiList = self.emoji
        for i in range(len(options)):
            options[i] = f"{emojiList[i]}- {options[i]}"
            embed.add_field(name=options[i], value="░░░░░░░░░░", inline=False)

        if channel and ctx.guild:
            if ctx.author.guild_permissions.manage_guild:
                if isinstance(channel, discord.TextChannel):
                    if not await utilities.checkPermsInChannel(ctx.guild.get_member(user_id=self.bot.user.id), channel):
                        return await ctx.send("Sorry, I am missing permissions in that channel.\n"
                                              "I need send messages, add reactions, manage messages, and embed links")
                    else:
                        msg = await channel.send(embed=embed)
                        await ctx.send("Sent :mailbox_with_mail:")
                else:
                    return await ctx.send(f"{channel.name} is not a text channel")
            else:
                await ctx.send("Sorry, to prevent abuse, only admins can set a destination channel")
                msg = await ctx.send(embed=embed)
        else:
            msg = await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

        for i in range(len(options)):
            await msg.add_reaction(emojiList[i])

    @tasks.loop(seconds=3)
    async def updatePoll(self):
        """Update the bars on polls
        We dont want to do this every time a reaction is added as we're gunna get rate limited almost constantly
        3 seconds is the maximum amount of time a user will consider fast, so every 3 seconds we update"""
        if len(self.pollsToUpdate) != 0:
            for item in self.pollsToUpdate.copy():
                # pop out the item when we update, so we re-check it in 3 seconds for no reason
                self.pollsToUpdate.remove(item)
                channel: discord.TextChannel = self.bot.get_channel(int(item[1]))
                if channel:
                    message: discord.Message = await self.bot.getMessage(messageID=int(item[0]), channel=channel)
                    if message:
                        originalEmbed = message.embeds[0]
                        embed = utilities.defaultEmbed(title=originalEmbed.title)
                        embed.set_footer(text=originalEmbed.footer.text, icon_url=originalEmbed.footer.icon_url)
                        # update fields
                        for i in range(len(originalEmbed.fields)):
                            emoji = originalEmbed.fields[i].name.split("-")[0]
                            embed.add_field(name=originalEmbed.fields[i].name,
                                            value=self.createBar(message, emoji), inline=False)
                        if embed != originalEmbed:
                            return await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                        else:
                            log.debug("No need to update")

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
                    if "1 response" in message.embeds[0].footer.text:
                        user = self.bot.get_user(payload.user_id)
                        for reaction in message.reactions:
                            if reaction.emoji != payload.emoji.name:
                                users = await reaction.users().flatten()
                                if user.id in [u.id for u in users]:
                                    await reaction.remove(user=user)

                # add this message to a set to bulk update shortly
                self.pollsToUpdate.add((payload.message_id, payload.channel_id))


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(Polls(bot))
    log.info("Polls mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning('Polls un-mounted')
    for handler in log.handlers[:]:
        log.removeHandler(handler)
