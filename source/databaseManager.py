import asyncio
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import time, sleep

import aiomysql
import sshtunnel

from . import utilities

log = utilities.getLog("database", logging.INFO)

if not os.path.isfile("data/DBLogin.json"):
    log.warning("Database login not present, please input")
    sleep(1)
    serverAddress = input("Server IP - ")
    serverPort = int(input("SSH Port - "))
    localAddress = input("Local Address - ")
    localPort = int(input("Local Port - "))
    sshUser = input("SSH User - ")
    DBUser = input("DB Username - ")
    DBPass = input("DB Password - ")

    data = {"serverAddress": serverAddress,
            "serverPort": serverPort,
            "localAddress": localAddress,
            "localPort": localPort,
            "sshUser": sshUser,
            "dbUser": DBUser,
            "dbPass": DBPass
            }
    f = open("data/DBLogin.json", "w")
    json.dump(data, f)
    f.close()

f = open("data/DBLogin.json", "r")
data = json.load(f)
f.close()
serverAddress = data['serverAddress']
serverPort = data['serverPort']
localAddress = data['localAddress']
localPort = data['localPort']
sshUser = data['sshUser']
DBUser = data['dbUser']
DBPass = data['dbPass']


class DBConnector:
    def __init__(self, loop=asyncio.get_event_loop()):
        self.tunnel = None
        self.loop = loop
        self.dbPool = None
        self.threadPool = ThreadPoolExecutor(max_workers=4)
        self.operations = 0
        self.time = Time

    def teardown(self):
        if self.tunnel:
            self.tunnel.close()
        self.threadPool.shutdown(wait=True)

    async def escape(self, inputString: str):
        """Escape the input"""
        async with self.dbPool.acquire() as conn:
            return conn.escape_string(inputString)

    def _connectToServer(self):
        """Creates a connection to the database server, be it via tunnel, if a tunnel isn't required, define tunnel as none"""
        if True:
            # If we're not on linux, the db ain't here, so we create an ssh tunnel to it
            # I ain't opening the db up to remote access, are you mad?
            tunnel = sshtunnel.open_tunnel((serverAddress, serverPort),
                                           ssh_username=sshUser,
                                           ssh_pkey="opensshkey.ppk",
                                           remote_bind_address=(localAddress, localPort),
                                           local_bind_address=(localAddress, localPort),
                                           logger=utilities.getLog("tunnel", logging.CRITICAL))
            tunnel.start()
            while not tunnel.is_active:
                # Wait for the tunnel to be considered active
                time.sleep(0.1)

            log.info(
                f"Connected to DB Server: {tunnel.is_active}. LocalAddr: {tunnel.local_bind_host}:{tunnel.local_bind_port}")
            self.tunnel = tunnel
        else:
            log.debug("Tunnel not required, running on host server")
            self.tunnel = None
            return

    async def _connectToDB(self):
        """Connects to the db, with a tunnel, or locally"""
        try:
            if self.tunnel:
                log.debug("Connecting to tunneled database")
                self.dbPool = await aiomysql.create_pool(
                    user=DBUser,
                    password=DBPass,
                    host=self.tunnel.local_bind_host,
                    port=self.tunnel.local_bind_port,
                    auth_plugin="mysql_native_password",
                    maxsize=10,
                )
            else:
                log.debug("Connecting to local database")
                self.dbPool = await aiomysql.create_pool(
                    user=DBUser,
                    password=DBPass,
                    host="127.0.0.1",
                    port=3306,
                    auth_plugin="mysql_native_password",
                    maxsize=10
                )

            # Configure db to accept emoji inputs (i wish users didnt do this, but i cant stop em)
            await self.execute('SET NAMES utf8mb4;')
            await self.execute('SET CHARACTER SET utf8mb4;')
            await self.execute('SET character_set_connection=utf8mb4;')

            databases = await self.execute("SHOW SCHEMAS")
            log.info(f"Database connection established. {len(databases)} schemas found")
            return True
        except Exception as e:
            log.critical(e)
            return False

    async def execute(self, query, getOne=False):
        """
        Execute a database operation
        :param query: the operation you want to make
        :param getOne: If you only want one item, set this to true
        :return: a dict of the operations return, or None
        """
        try:
            log.debug(f"Executing query - {query}")
            if self.tunnel:
                if not self.tunnel.is_active:
                    # If we lose the tunnel, wait a short while, and try and reconnect
                    log.warning("Detected DB Tunnel Closed, waiting 30 seconds before attempting to re-connect")
                    while not self.tunnel.is_active:
                        await asyncio.sleep(30)
                        log.warning("Attempting to re-establish DB Tunnel")
                        try:
                            await self.loop.run_in_executor(self.threadPool, self._connectToServer)
                        except Exception as e:
                            log.error(e)
                    log.debug(
                        "Tunnel re-opened. Assuming server restart, waiting 30 seconds before resuming operations")
                    await asyncio.sleep(30)
                    log.debug(f"Resubmitting query: {query}")

            try:
                async with self.dbPool.acquire() as conn:
                    log.debug("Validating connection")
                    await conn.ping(reconnect=True)  # ping the database, to make sure we have a connection
            except Exception as e:
                log.error(f"{e}")
                await asyncio.sleep(5)  # sleep for a few seconds
                await self.connect()  # Attempt to reconnect

            async with self.dbPool.acquire() as conn:
                async with conn.cursor(aiomysql.SSDictCursor) as cur:
                    try:
                        self.operations += 1  # useless, but i like to track how many operations im making

                        await cur.execute(query)  # execute the query
                        if not getOne:
                            result = await cur.fetchall()
                        else:
                            result = await cur.fetchone()
                    except Exception as e:
                        raise e
                    if isinstance(result, tuple):
                        if len(result) == 0:
                            return None
                    await cur.close()
                await conn.commit()
            return result
        except Exception as e:
            try:
                cur.close()
            except:
                pass
            log.error(e)
            if "cannot connect" in str(e):
                await asyncio.sleep(1)
                await self.execute(query=query, getOne=getOne)

    async def connect(self):
        """Public function to connect to the database"""
        if self.tunnel:
            if not self.tunnel.is_active:
                await self.loop.run_in_executor(self.threadPool, self._connectToServer)
        else:
            await self.loop.run_in_executor(self.threadPool, self._connectToServer)

        await self._connectToDB()


class Time:
    """\
*Convenience class for easy format conversion*
Accepts time() float, datetime object, or SQL datetime str.
If no time arg is provided, object is initialized with time().
id kwarg can be used to keep track of objects.
Access formats as instance.t, instance.dt, or instance.sql.

https://stackoverflow.com/a/59906601
    """

    f = '%Y-%m-%d %H:%M:%S'

    def __init__(self, *arg, id=None) -> None:
        self.id = id
        if len(arg) == 0:
            self.t = time()
            self.dt = self._dt
            self.sql = self._sql
        else:
            arg = arg[0]
            if isinstance(arg, float) or arg == None:
                if isinstance(arg, float):
                    self.t = arg
                else:
                    self.t = time()
                self.dt = self._dt
                self.sql = self._sql
            elif isinstance(arg, datetime):
                self.t = arg.timestamp()
                self.dt = arg
                self.sql = self._sql
            elif isinstance(arg, str):
                self.sql = arg
                if '.' not in arg:
                    self.dt = datetime.strptime(self.sql, Time.f)
                else:
                    normal, fract = arg.split('.')
                    py_t = datetime.strptime(normal, Time.f)
                    self.dt = py_t.replace(
                        microsecond=int(fract.ljust(6, '0')[:6]))
                self.t = self.dt.timestamp()

    @property
    def _dt(self) -> datetime:
        return datetime.fromtimestamp(self.t)

    @property
    def _sql(self) -> str:
        t = self.dt
        std = t.strftime(Time.f)
        fract = f'.{str(round(t.microsecond, -3))[:3]}'
        return std + fract

    def __str__(self) -> str:
        if self.id == None:
            return self.sql
        else:
            return f'Time obj "{self.id}": {self.sql}'
