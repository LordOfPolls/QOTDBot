import asyncio
import logging
import random
import discord_slash.error
from collections import Counter
from datetime import datetime

import discord
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers import cron
from discord.ext import commands, tasks
from discord_slash import cog_ext, SlashContext
from discord_slash.utils import manage_commands
from fuzzywuzzy import fuzz

from source import utilities, dataclass, checks, jsonManager

log = utilities.getLog("Cog::qotd")
log.setLevel(logging.DEBUG)


class QOTD(commands.Cog):
    """The QOTD system"""

    def __init__(self, bot: dataclass.Bot):
        self.bot = bot
        self.emoji = "❓"

        # i know i could use tasks, however i dont want to use interval scheduling, due to the
        # chance it can fail if not checked second by second
        self.scheduler = AsyncIOScheduler()  # the task scheduler

    async def rescheduleTask(self, guildID):
        """Reschedules a task"""
        guildID = str(guildID)
        guildData = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.guilds WHERE guildID = '{guildID}'", getOne=True
        )
        time = utilities.convertTime(guildData["timeZone"], guildData["sendTime"])
        try:
            self.scheduler.reschedule_job(
                job_id=guildID, trigger=cron.CronTrigger(hour=time.hour, minute=0)
            )
            log.debug(f"Job {guildID} rescheduled to {time.hour:02}:{time.minute:02}")
        except JobLookupError:
            # if job doesnt exist, create one
            self.scheduler.add_job(
                id=str(guildID),
                name=f"QOTD TASK FOR {guildID}",
                trigger=cron.CronTrigger(hour=time.hour, minute=time.minute),
                func=self.sendTask,
                kwargs={"guildID": guildID},
            )
            log.debug(f"Job {guildID} created for {time.hour:02}:{time.minute:02}")
        except Exception as e:
            log.error(f"Failed to reschedule job:{guildID}. Reason: {e}")

    async def setup(self):
        """Creates the jobs for sending qotd to servers"""
        try:
            guilds = await self.bot.db.execute(f"SELECT * FROM QOTDBot.guilds")
            for guild in guilds:
                try:
                    if bool(guild["enabled"]):
                        if (
                            guild["qotdChannel"] is not None
                            and guild["timeZone"] is not None
                            and guild["sendTime"] is not None
                        ):
                            # "if all required vars are set"
                            if self.bot.get_guild(int(guild["guildID"])):
                                qotdChannel = self.bot.get_channel(
                                    int(guild["qotdChannel"])
                                )
                                if qotdChannel:
                                    timeZone = guild["timeZone"]
                                    sendTime = guild["sendTime"]

                                    # convert time to local time and schedule a task
                                    time = utilities.convertTime(timeZone, sendTime)
                                    job = self.scheduler.add_job(
                                        id=str(guild["guildID"]),
                                        name=f"QOTD TASK FOR {guild['guildID']}",
                                        trigger=cron.CronTrigger(
                                            hour=time.hour, minute=time.minute
                                        ),
                                        func=self.sendTask,
                                        kwargs={"guildID": guild["guildID"]},
                                    )

                                    log.debug(
                                        f"Created job {job.id} @ {time.hour:02}:{time.minute:02} [{timeZone}:{sendTime:02}:00]"
                                    )
                except Exception as e:
                    log.critical(
                        f"Error while creating QOTD job for {guild['guildID']}: {e}"
                    )
            log.info("Starting AIOScheduler")
            self.scheduler.start()
        except Exception as e:
            log.critical(f"Error while setting up QOTD job: {e}")

    async def checkSimilarity(self, ctx, question, mode, embed):
        # prevent duplicate questions being added
        questPool = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.questions WHERE guildID = '{mode}'"
        )
        if len(questPool) > 0:
            results = {}
            for _quest in questPool:
                fuzzResult = fuzz.ratio(
                    question.lower(), _quest["questionText"].lower()
                )
                results[_quest["questionText"]] = fuzzResult
            # mostSimilar = max(results, key=results.get)

            topQuestions = Counter(results)
            mostSimilar = topQuestions.most_common(3)
            mostSimilarList = []
            for _q in mostSimilar:
                if _q[1] >= 80:
                    mostSimilarList.append(_q[0])

            if mostSimilarList:
                # add top 3 matches to list
                _emb = embed.copy()
                _emb.colour = discord.Colour.dark_orange()
                _emb.title = "Similar Question Found:"
                if len(mostSimilarList) > 1:
                    _emb.title = "Similar Questions Found:"
                _emb.description = ""
                for _q in mostSimilarList:
                    _emb.description += f"- `{_q}`\n"
                _emb.description += "\nWould you like to add anyway?"
                message = await ctx.send(embed=_emb)
                accept = await utilities.YesOrNoReactionCheck(ctx, message)
                if not accept:
                    await message.edit(
                        embed=utilities.defaultEmbed(
                            colour=discord.Colour.dark_red(), title="Cancelled 👌"
                        )
                    )
                    return False
        return True

    @commands.check(checks.checkAll)
    @cog_ext.cog_slash(**jsonManager.getDecorator("add"))
    async def cmdAddQuestion(self, ctx: SlashContext, *, question: str):
        """Checks if question is a duplicate, if not, adds to qotd pool"""
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        mode = ctx.guild.id
        embed = utilities.defaultEmbed(title="Adding Question")
        embed.set_footer(
            icon_url=self.bot.user.avatar_url,
            text=f"{self.bot.user.name} • Custom Questions",
        )

        if await self.checkSimilarity(ctx, question, mode, embed):
            question = await self.bot.db.escape(question)
            await self.bot.db.execute(
                f"INSERT INTO QOTDBot.questions (questionText, guildID) "
                f"VALUES ('{question}', '{mode}')"
            )
            embed.title = "Added Question"
            await ctx.send(embed=embed)

    @commands.check(checks.checkAll)
    @cog_ext.cog_slash(**jsonManager.getDecorator("send"))
    async def cmdManualSend(self, ctx: SlashContext):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        info = await self.bot.db.execute(
            f"SELECT qotdChannel FROM QOTDBot.guilds WHERE guildID = '{ctx.guild.id}'",
            getOne=True,
        )
        channel = self.bot.get_channel(int(info["qotdChannel"]))
        if not channel:
            return await ctx.send(
                "There was an error accessing your qotd channel, do i have permission to send in it?"
            )
        if await self.onPost(ctx.guild, channel):
            await ctx.send("Sent :mailbox_with_mail:")
        else:
            await ctx.send("Failed to send in qotd channel. Check permissions")

    @commands.check(checks.checkAll)
    @cog_ext.cog_slash(**jsonManager.getDecorator("remaining"))
    async def cmdQuestionsLeft(self, ctx: SlashContext):
        if not await checks.checkAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        customQuestions = await self.bot.db.execute(
            f"""SELECT COUNT(*) FROM QOTDBot.questions
WHERE questions.guildID = '{ctx.guild.id}' AND questionID NOT IN (
SELECT questionLog.questionID FROM QOTDBot.questionLog WHERE questionLog.guildID = '{ctx.guild.id}'
)""",
            getOne=True,
        )

        defaultQuestions = await self.bot.db.execute(
            f"""SELECT COUNT(*) FROM QOTDBot.questions
WHERE questions.guildID = '0' AND questionID NOT IN (
SELECT questionLog.questionID FROM QOTDBot.questionLog WHERE questionLog.guildID = '{ctx.guild.id}'
)""",
            getOne=True,
        )

        customQuestions = customQuestions["COUNT(*)"]
        defaultQuestions = defaultQuestions["COUNT(*)"]

        _emb = utilities.defaultEmbed(title="Remaining questions")
        _emb.add_field(name="Default Questions:", value=defaultQuestions)
        _emb.add_field(name="Custom Questions:", value=customQuestions)

        _emb.set_footer(
            text="These are questions that have not been asked in your server yet"
        )

        await ctx.send(embed=_emb)

    @commands.check(checks.checkUserAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("suggestion.add"))
    async def slashSuggest(
        self,
        ctx: SlashContext,
        question: str,
        hidequestion: str = "False",
        defaultQuestion: bool = False,
    ):
        if not await checks.checkUserAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        HideQuestion = True if hidequestion == "True" else False
        await ctx.defer(hidden=HideQuestion)
        question = await self.bot.db.escape(question)
        await self.bot.db.execute(
            f"INSERT INTO QOTDBot.suggestedQuestions (question, authorID, guildID) VALUES "
            f"('{question}', {ctx.author.id}, {ctx.guild.id})"
        )
        if HideQuestion:
            await ctx.send(content="Your question has been submitted")
        else:
            await ctx.send(
                embed=utilities.defaultEmbed(
                    title=f"Your Question Has Been Submitted",
                    colour=discord.Colour.green(),
                )
            )

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("suggestion.list"))
    async def slashListSuggestions(self, ctx: SlashContext):
        if not await checks.checkUserAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        data = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.suggestedQuestions WHERE guildID = '{ctx.guild.id}'"
        )
        emb = utilities.defaultEmbed(title="Suggested Questions")

        questions = []
        question = 1
        for questionData in data:
            author = self.bot.get_user(id=int(questionData["authorID"]))
            authorName = author.name if author is not None else "Unknown"
            questions.append(
                f"`{question}.` {questionData['question']}\n`Submitted by {authorName}`"
            )
            question += 1

        pageNum = 0
        await utilities.paginator.LinePaginator.paginate(
            questions, ctx=ctx, embed=emb, max_lines=10, empty=False
        )

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("suggestion.approve"))
    async def slashApproveSuggestion(self, ctx: SlashContext, questionid: int):
        if not await checks.checkUserAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        data = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.suggestedQuestions WHERE guildID = '{ctx.guild.id}'"
        )
        emb = utilities.defaultEmbed(title="Approved Question")

        questions = []
        question = 1
        for questionData in data:
            questions.append(questionData)
            question += 1
        if questionid > question or questionid <= 0:
            return await ctx.send("No question found with that ID")

        try:
            questData = questions[questionid - 1]
        except IndexError:
            return await ctx.send("No question found with that ID")
        author = self.bot.get_user(id=int(questData["authorID"]))

        try:
            if await self.checkSimilarity(
                ctx, questData["question"], ctx.guild.id, emb
            ):
                question = await self.bot.db.escape(questData["question"])
                await self.bot.db.execute(
                    f"DELETE FROM QOTDBot.suggestedQuestions WHERE suggestionID = {questData['suggestionID']}"
                )
                await self.bot.db.execute(
                    f"INSERT INTO QOTDBot.questions (questionText, guildID) "
                    f"VALUES ('{question}', '{ctx.guild.id}')"
                )
            else:
                return
        except Exception as e:
            log.error(e)
            return await ctx.send(
                "Failed to process question... Please try again later :cry:"
            )
        else:
            emb.description = questData["question"]
            if author:
                emb.set_footer(
                    text=f"Submitted by {author.name}", icon_url=author.avatar_url
                )
            await ctx.send(embed=emb)

    @commands.check(checks.checkAll)
    @cog_ext.cog_subcommand(**jsonManager.getDecorator("suggestion.reject"))
    async def slashDenySuggestion(self, ctx: SlashContext, questionid: int):
        if not await checks.checkUserAll(ctx):  # decorators arent 100% reliable yet
            raise discord_slash.error.CheckFailure
        await ctx.defer()
        data = await self.bot.db.execute(
            f"SELECT * FROM QOTDBot.suggestedQuestions WHERE guildID = '{ctx.guild.id}'"
        )
        emb = utilities.defaultEmbed(title="Rejected Question")

        questions = []
        question = 1
        for questionData in data:
            questions.append(questionData)
            question += 1
        if questionid > question or questionid <= 0:
            return await ctx.send("No question found with that ID")

        try:
            questData = questions[questionid - 1]
        except IndexError:
            return await ctx.send("No question found with that ID")
        author = self.bot.get_user(id=int(questData["authorID"]))

        try:
            await self.bot.db.execute(
                f"DELETE FROM QOTDBot.suggestedQuestions WHERE suggestionID = {questData['suggestionID']}"
            )
        except Exception as e:
            log.error(e)
            return await ctx.send(
                "Failed to process question... Please try again later :cry:"
            )
        else:
            emb.description = questData["question"]
            if author:
                emb.set_footer(
                    text=f"Submitted by {author.name}", icon_url=author.avatar_url
                )
            await ctx.send(embed=emb)

    async def onPost(
        self,
        guild: discord.Guild,
        qotdChannel: discord.TextChannel,
        rolesToMention=None,
        customPriority: bool = False,
    ):
        """Selects a question to be posted, from both the default list and custom list"""
        qotdMessage = None

        try:
            await qotdChannel.trigger_typing()
            question = None
            source = "Default Question"
            guildConfig = await self.bot.db.execute(
                f"SELECT * FROM QOTDBot.guilds WHERE guildID = '{guild.id}'",
                getOne=True,
            )
            # get question from DB
            customQuestion = await self.bot.db.execute(
                "SELECT * FROM QOTDBot.questions "
                f"WHERE guildID = '{guild.id}' AND questionID NOT IN ("
                f"SELECT questionID FROM QOTDBot.questionLog "
                f"WHERE questionLog.guildID = '{guild.id}')"
                f"ORDER BY RAND() LIMIT 1",
                getOne=True,
            )

            defaultQuestion = await self.bot.db.execute(
                "SELECT * FROM QOTDBot.questions "
                f"WHERE guildID = '0' AND questionID NOT IN ("
                f"SELECT questionID FROM QOTDBot.questionLog "
                f"WHERE questionLog.guildID = '{guild.id}')"
                f"ORDER BY RAND() LIMIT 1",
                getOne=True,
            )
            if customQuestion:
                source = "Custom Question"
                question = customQuestion
            elif defaultQuestion:
                source = "Default Question"
                question = defaultQuestion
            else:
                return log.error("No questions left!")

            emb = discord.Embed(colour=discord.Colour.blurple())
            if len(question["questionText"]) > 200:
                emb.description = question["questionText"]
                emb.title = "Question of The Day"
            else:
                emb.title = question["questionText"]
            emb.set_footer(
                icon_url=self.bot.user.avatar_url,
                text=f"{self.bot.user.name} • {source}",
            )
            try:
                qotdMessage = await qotdChannel.send(embed=emb)

                # if guild wants qotd pinning
                if guildConfig["pinMessage"] == 1:
                    await qotdMessage.pin(reason="/setup pin is enabled")

                # if guild wants a role to be pinged, this ghost pings them
                if guildConfig["mentionRole"] is not None:
                    role: discord.Role = guild.get_role(int(guildConfig["mentionRole"]))
                    if role:
                        msg = await qotdChannel.send(
                            role.mention, allowed_mentions=discord.AllowedMentions.all()
                        )
                        await asyncio.sleep(1)
                        await msg.delete()

            except Exception as e:
                if qotdMessage is not None:
                    await self.bot.db.execute(
                        f"INSERT INTO QOTDBot.questionLog (questionID, guildID, posted, datePosted) "
                        f"VALUES ({question['questionID']}, '{guild.id}', TRUE, '{datetime.now()}')"
                    )
                    if "maximum number of pins" in str(e).lower():
                        await qotdMessage.edit(
                            content="⚠ Unable to pin: maximum pins in channel"
                        )
                    return True
                else:
                    log.error(f"Unable to post question to {guild.id}: {e}")
            else:
                await self.bot.db.execute(
                    f"INSERT INTO QOTDBot.questionLog (questionID, guildID, posted, datePosted) "
                    f"VALUES ({question['questionID']}, '{guild.id}', TRUE, '{datetime.now()}')"
                )
                return True
        except discord.Forbidden:
            try:
                await guild.owner.send(
                    "An error occurred while trying to send your question, "
                    "I am missing permissions in your requested channel. Please make sure I can "
                    "send messages, manage messages, embed links, and add reactions in the desired channel"
                )
            except:
                try:
                    await guild.system_channel.send(
                        "An error occurred while trying to send your question, "
                        "I am missing permissions in your requested channel. Please make sure I can "
                        "send messages, manage messages, embed links, and add reactions in the desired channel"
                    )
                except:
                    pass
            log.error(f"Missing permissions to send qotd in {guild.id}: {guild.name}")
            return False

    async def sendTask(self, guildID):
        """The scheduled task for sending qotd"""
        me = self.scheduler.get_job(job_id=str(guildID))
        _guild = await self.bot.db.execute(
            "SELECT * FROM QOTDBot.guilds " f"WHERE guildID = '{guildID}'", getOne=True
        )
        try:
            if _guild["enabled"] == 0:
                log.debug(f"{guildID} disabled qotd, not sending")
                return
        except TypeError:
            # for some reason this guild isnt in our DB? We should check if we're even still in the guild
            guild = self.bot.get_guild(int(guildID))
            if not guild:
                # guild gone, delete this job
                log.warning(f"Can no longer access {guildID}, cancelling job")
                me.remove()
                return
        guild = self.bot.get_guild(int(guildID))
        if guild:
            qotdChannel = _guild["qotdChannel"]
            qotdChannel = self.bot.get_channel(int(qotdChannel))
            if qotdChannel:
                await self.onPost(guild, qotdChannel)

        else:
            log.warning(f"Can no longer access {guildID}, cancelling job")
            me.remove()
            return
        log.debug(f"Job for {guildID} has run, next run at {me.next_run_time}")


def setup(bot):
    """Called when this cog is mounted"""
    bot.add_cog(QOTD(bot))
    log.info("QOTD mounted")


def teardown(bot):
    """Called when this cog is unmounted"""
    log.warning("QOTD un-mounted")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
