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
        super().__init__(*args, **kwargs)