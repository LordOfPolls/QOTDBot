import asyncio
import databaseManager

loop = asyncio.get_event_loop()
db = databaseManager.DBConnector()
asyncio.run_coroutine_threadsafe(db.connect, loop).result()
