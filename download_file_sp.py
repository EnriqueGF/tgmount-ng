from telethon import TelegramClient
import asyncio
import sys

async def download_chunk_from_message(client, chat_id, message_id, offset, size):
    chat = await client.get_entity(chat_id)
    message = await client.get_messages(chat, ids=message_id)
    
    if message and message.media:
        async for chunk in client.iter_download(message.media, offset=offset, limit=size):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()

api_id = '26936788'
api_hash = 'e82daf5a0f06b89957dc86f0120d73b9'
session_file = 'tgfs.session2'
client = TelegramClient(session_file, api_id, api_hash)

async def main():
    chat_id = -4038726918
    
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            continue
        message_id, offset, size = map(int, line.split())
        
        await download_chunk_from_message(client, chat_id, message_id, offset, size)

with client:
    client.loop.run_until_complete(main())
