from telethon import TelegramClient
import asyncio
import sys

async def download_chunk_from_message(client, chat_id, message_id, offset, size):
    chat = await client.get_entity(chat_id)
    message = await client.get_messages(chat, ids=message_id)
    
    downloaded = b""
    request_size = 1 * 1024 * 1024  # 1 MB
    
    if message and message.media:
        print(f"Solicito chunk: {offset} {size}")
        async for chunk in client.iter_download(message.media, offset=offset, limit=size, request_size=request_size):
            downloaded += chunk
            
            if len(downloaded) >= size:
                break

    return downloaded[:size]
            
api_id = '26936788'
api_hash = 'e82daf5a0f06b89957dc86f0120d73b9'
session_file = 'tgfs.session2'
client = TelegramClient(session_file, api_id, api_hash)
chat_id = -4038726918

async def main():
    #await test(); quit();
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            continue
        message_id, offset, size = map(int, line.split())
        
        requestedBytes = await download_chunk_from_message(client, chat_id, message_id, offset, size)
        sys.stdout.buffer.write(requestedBytes)
        sys.stdout.buffer.flush()
        #sys.stdout.buffer.close()

async def test():
    line = '1597157 196608 131072'
    message_id, offset, size = map(int, line.split())
    
    bytesData = await download_chunk_from_message(client, chat_id, message_id, offset, size)
    print(bytesData)
    print(len(bytesData))

with client:
    client.loop.run_until_complete(main())
