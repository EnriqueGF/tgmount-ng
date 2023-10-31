import subprocess

chunk_size = 128 * 1024  
total_size = 20 * 1024 * 1024  # Tamaño total para descargar en bytes (10 MB)

proc = subprocess.Popen(
    ["python", "download_file_sp.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    bufsize=0,
)

offset = 720896
total_data = b""
messageId = 1597157

def getChunk(off, size):
    chunk_info = f"{messageId} {off} {size}\n"
    print(f"Solicitado a download_file_sp: {chunk_info}")
    proc.stdin.write(chunk_info.encode())
    proc.stdin.flush()

    received_data = b""
    remaining_size = size

    while remaining_size > 0:
        chunk = proc.stdout.read(min(remaining_size, 65536))  # Lee hasta 64KB de una vez
        received_data += chunk
        remaining_size -= len(chunk)

    return received_data
        
        
response = getChunk(offset, 131072)

print(f"Received: {len(response)} bytes")
 
print(response)
 
proc.wait()

