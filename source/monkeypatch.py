import asyncio
import copy
import datetime
import inspect
import traceback
import typing

import discord
import discord_slash
from discord.ext.commands import CooldownMapping, CommandOnCooldown
from discord.utils import snowflake_time
from discord_slash import model

from source import utilities

# i am more than aware monkey patching is not a good idea, but i really dont care
# the only downside is i have to maintain this and it might break when the lib updates
# hate me silently or piss off


log = utilities.getLog("MonkeyPatcher")

# create copies so i can call the original inits
context_original_init = copy.copy(discord_slash.context.SlashContext.__init__)
commandObj_original_init = copy.copy(discord_slash.model.CommandObject.__init__)


def monkeypatched_SlashCommand(*args, **kwargs) -> discord_slash.SlashCommand:
    """The discord_slash SlashCommands lib with some features monkey patched in

    Adds error decorators, custom invoker, cooldowns and fixes Type Error bug"""
    try:
        # patch commandObjects
        log.debug("Patching model.CommandObject...")
        # Adds error decorator support
        discord_slash.model.CommandObject.error = error
        # Cooldown / max concurrency support
        discord_slash.model.CommandObject.__init__ = command_init
        discord_slash.model.CommandObject._prepare_cooldowns = _prepare_cooldowns
        discord_slash.model.CommandObject._concurrency_checks = _concurrency_checks
        discord_slash.model.CommandObject.invoke = invoke
        discord_slash.model.CommandObject.is_on_cooldown = is_on_cooldown
        discord_slash.model.CommandObject.reset_cooldown = reset_cooldown
        discord_slash.model.CommandObject.get_cooldown_retry_after = (
            get_cooldown_retry_after
        )

        log.debug("Patching model.CogCommandObject...")
        # Cooldown / max concurrency support
        discord_slash.model.CogBaseCommandObject.invoke = invoke

        log.debug("Patching model.CogSubcommandObject...")
        # Cooldown / max concurrency support
        discord_slash.model.CogSubcommandObject.invoke = invoke

        # patch context
        log.debug("Patching context.SlashContext...")
        # Cooldown / max concurrency support
        discord_slash.context.SlashContext.__init__ = context_init

        # replace invoke_command
        log.debug("Patching invoke_command...")
        # Error decorator support and bug fix
        discord_slash.SlashCommand.invoke_command = slsh_invoke_command

        # adding slash command perms cache
        discord_slash.SlashCommand.perms_cache = {}

        log.info("Successfully patched discord_slash.SlashCommand")
        return discord_slash.SlashCommand(*args, **kwargs)
    except Exception as e:
        log.error(
            "Failed to patch discord_slash.SlashCommand:\n{}".format(
                "".join(traceback.format_exception(type(e), e, e.__traceback__))
            )
        )
        exit(1)


# region init


def context_init(self, _http, _json: dict, _discord, logger):
    context_original_init(self, _http, _json, _discord, logger)
    self.created_at = snowflake_time(
        int(self.interaction_id)
    )  # the time this interaction was created


def command_init(self, name, cmd):
    commandObj_original_init(self, name, cmd)

    # add in cooldowns and concurrency attribs
    cooldown = None
    if hasattr(self.func, "__commands_cooldown__"):
        cooldown = self.func.__commands_cooldown__
    self._buckets = CooldownMapping(cooldown)

    self._max_concurrency = None
    if hasattr(self.func, "__commands_max_concurrency__"):
        self._max_concurrency = self.func.__commands_max_concurrency__


# endregion


def error(cmd, coro):
    if not asyncio.iscoroutinefunction(coro):
        raise TypeError("The error handler must be a coroutine.")

    cmd.on_error = coro
    return coro


async def slsh_invoke_command(self, func, ctx, args):
    """
    Invokes command.

    :param func: Command coroutine.
    :param ctx: Context.
    :param args: Args. Can be list or dict.
    """
    try:
        if isinstance(args, dict):
            await func.invoke(ctx, **args)
        else:
            await func.invoke(ctx, *args)
    except Exception as ex:
        if hasattr(func, "on_error"):
            # call error decorator
            try:
                # i hate that i need to do this, but welcome to the joy of monkey patching
                # this basically checks if the error decorator needs a reference to self passing
                if "self" in inspect.signature(func.on_error).parameters:
                    await func.on_error(func.cog, ctx, ex)
                    return
                else:
                    await func.on_error(ctx, ex)
                    return
            except Exception as e:
                self.logger.error(f"{ctx.command}:: Error using error decorator: {e}")
        await self.on_slash_command_error(ctx, ex)


def check_perms(
    slash: discord_slash.SlashCommand, func, ctx: discord_slash.SlashContext
):
    """Checks if the user invoking a command should actually have access
    A discord exploit makes this necessary"""
    if isinstance(func, discord_slash.model.CogSubcommandObject):
        base_cmd: dict = func.base_command_data
        if base_cmd.get("default_permission") is True:
            return True
    else:
        if func.default_permission is True:
            return True
    # i dont use non-cog commands, so i cant be bothered to explicitly handle them

    # check for role / user
    if perms := slash.perms_cache.get(ctx.guild.id):
        for role in ctx.author.roles:
            role: discord.Role
            if role.id in perms:
                return True
    return False


# region Cooldown code


def _prepare_cooldowns(self, ctx):
    """
    Ref https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/core.py#L765
    """
    if self._buckets.valid:
        dt = ctx.created_at
        current = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        bucket = self._buckets.get_bucket(ctx, current)
        retry_after = bucket.update_rate_limit(current)
        if retry_after:
            raise CommandOnCooldown(bucket, retry_after)


async def _concurrency_checks(self, ctx):
    """The checks required for cooldown and max concurrency."""
    # max concurrency checks
    if self._max_concurrency is not None:
        await self._max_concurrency.acquire(ctx)
    try:
        # cooldown checks
        self._prepare_cooldowns(ctx)
    except:
        if self._max_concurrency is not None:
            await self._max_concurrency.release(ctx)
        raise


async def invoke(self, *args, **kwargs):
    """
    Invokes the command.
    :param args: Args for the command.
    :raises: .error.CheckFailure
    """
    can_run = await self.can_run(args[0])
    if not can_run:
        raise discord_slash.model.error.CheckFailure

    await self._concurrency_checks(args[0])

    # to preventing needing different functions per object,
    # this function simply handles cogs
    if hasattr(self, "cog"):
        return await self.func(self.cog, *args, **kwargs)
    return await self.func(*args, **kwargs)


def is_on_cooldown(self, ctx):
    """Checks whether the command is currently on cooldown.
    Ref https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/core.py#L797
    Parameters
    -----------
    ctx: :class:`.Context`
        The invocation context to use when checking the commands cooldown status.
    Returns
    --------
    :class:`bool`
        A boolean indicating if the command is on cooldown.
    """
    if not self._buckets.valid:
        return False

    bucket = self._buckets.get_bucket(ctx.message)
    dt = ctx.message.edited_at or ctx.message.created_at
    current = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    return bucket.get_tokens(current) == 0


def reset_cooldown(self, ctx):
    """Resets the cooldown on this command.
    Ref https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/core.py#L818
    Parameters
    -----------
    ctx: :class:`.Context`
        The invocation context to reset the cooldown under.
    """
    if self._buckets.valid:
        bucket = self._buckets.get_bucket(ctx.message)
        bucket.reset()


def get_cooldown_retry_after(self, ctx):
    """Retrieves the amount of seconds before this command can be tried again.
    Ref https://github.com/Rapptz/discord.py/blob/master/discord/ext/commands/core.py#L830
    Parameters
    -----------
    ctx: :class:`.Context`
        The invocation context to retrieve the cooldown from.
    Returns
    --------
    :class:`float`
        The amount of time left on this command's cooldown in seconds.
        If this is ``0.0`` then the command isn't on cooldown.
    """
    if self._buckets.valid:
        bucket = self._buckets.get_bucket(ctx.message)
        dt = ctx.message.edited_at or ctx.message.created_at
        current = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        return bucket.get_retry_after(current)

    return 0.0


# endregion
