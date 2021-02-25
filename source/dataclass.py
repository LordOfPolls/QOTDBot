import discord
from discord.ext import commands

from . import databaseManager


class Bot(commands.Bot):
    """Expands on the default bot class, and helps with type-hinting """

    def __init__(self, cogList=list, *args, **kwargs):
        self.cogList = cogList
        """A list of cogs to be mounted"""

        self.db = databaseManager.DBConnector()
        """The bots database"""

        self.appInfo: discord.AppInfo = None
        """A cached application info"""

        self.startTime = None
        """The time the bot started"""

        self.shouldUpdateBL = True
        """Should the bot try and update bot-lists"""

        super().__init__(*args, **kwargs)

    async def getMessage(self, messageID: int, channel: discord.TextChannel) -> (discord.Message, None):
        """Gets a message using the id given"""
        for message in self.cached_messages:
            # Check if the message is in the cache to save querying discord
            if message.id == messageID:
                return message

        # try and find the message in the channel
        o = discord.Object(id=messageID + 1)
        msg = await channel.history(limit=1, before=o).next()
        if messageID == msg.id:
            return msg
        return None
