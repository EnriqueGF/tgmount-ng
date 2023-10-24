import errno
import os
from dataclasses import dataclass, replace
from typing import Any, Optional, TypedDict, overload

import pyfuse3
from datetime import datetime
from tgmount import vfs
from tgmount.util import none_fallback, measure_time
from tgmount.vfs.util import MyLock
from .fh import FileSystemHandles
from .inode import InodesRegistry, RegistryItem, RegistryRoot
from .util import (
    create_directory_attributes,
    create_file_attributes,
    exception_handler,
    flags_to_str,
)

import mmap
import time
import asyncio
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, TimeoutError

""" 
TODO
lookup coconut

"""


@dataclass
class FileSystemItem:
    structure_item: vfs.DirContentItem
    attrs: pyfuse3.EntryAttributes

    def __repr__(self) -> str:
        return f"FileSystemItem({self.structure_item})"

    def set_structure_item(self, structure_item: vfs.DirContentItem):
        return replace(self, structure_item=structure_item)


InodesRegistryItem = RegistryItem[FileSystemItem] | RegistryRoot[FileSystemItem]


InodesTreeFile = TypedDict(
    "InodesTreeFile", inode=int, path=list[str], path_str=str, name=str, extra=Any
)

InodesTree = TypedDict(
    "InodesTree",
    inode=int,
    name=str,
    path=list[str],
    path_str=str,
    extra=Any,
    children=Optional[list["InodesTree | InodesTreeFile"]],
)


class FileSystemOperationsMixin:
    def get_inodes_tree(
        self: "FileSystemOperations", inode=InodesRegistry.ROOT_INODE  # type: ignore
    ) -> InodesTree:
        item = self.inodes.get_item_by_inode(inode)

        if item is None:
            raise ValueError(f"item with {inode} was not found")

        inodes = self.inodes

        path = none_fallback(inodes.get_item_path(inode), [])

        children = None
        if self.inodes.was_content_read(inode):
            children = []
            children_items = inodes.get_items_by_parent(inode)

            if children_items is None:
                children_items = []

            for child in children_items:
                if isinstance(child.data.structure_item, vfs.DirLike):
                    children.append(self.get_inodes_tree(child.inode))
                else:
                    path = [*path, child.name]
                    children.append(
                        InodesTreeFile(
                            inode=child.inode,
                            path=list(map(self._bytes_to_str, path)),
                            path_str=inodes.join_path(path).decode("utf-8"),
                            name=self._bytes_to_str(child.name),
                            extra=child.data.structure_item.extra,
                        )
                    )

        return InodesTree(
            inode=inode,
            name=self._bytes_to_str(item.name),
            path=list(map(self._bytes_to_str, path)),
            path_str=self._bytes_to_str(inodes.join_path(path)),
            children=children,
            extra=item.data.structure_item.extra,
        )


from .logger import logger

class MemoryBuffer:
    def __init__(self):
        self.bufferArray = {}
        self.writtenRanges = {}
        self.isBufferingList = {}
        self.bufferingTasks = {}
    
    def storeFile(self, handle, bytes):
        self.bufferArray[handle] = mmap.mmap(-1, bytes, access=mmap.ACCESS_WRITE)
        self.writtenRanges[handle] = set()
        self.isBufferingList[handle] = False
        
    async def memoryRead(self, handle, off, size, item):
        if handle not in self.bufferArray:
            print("(Buffer) Error: handle not found")
            return None
        
        totalFilesize = item.data.structure_item.content.size;

        ## OPERACIONES EN EL CASO DE QUE SE SOLICITE UN OFFSET MAYOR AL TAMAÑO DEL ARCHIVO
        if off >= totalFilesize:
            print('\033[93m' + "(Buffer) ENTRO1 OPERACIONES EN EL CASO DE QUE SE SOLICITE UN OFFSET MAYOR AL TAMAÑO DEL ARCHIVO" + '\033[0m')
            return await item.data.structure_item.content.read_func(handle, off, size);

        if off + size > totalFilesize:
            print('\033[93m' + "(Buffer) RETORNO B'' PORQUE EL OFFSET + SIZE ES MAYOR AL TAMAÑO DEL ARCHIVO" + '\033[0m')
            return await item.data.structure_item.content.read_func(handle, off, size);

        attempts = 0;
      
        while not self.hasBeenWritten(handle, off, size) and attempts < 50:
            #print(f"Waiting for data to be available. handle={handle}, off={off}, size={size}")
            #print(f"Written ranges: {self.writtenRanges[handle]}")
            attempts += 1
            #print(f"SUMADO ATTEMPT, attempts {attempts} llamado desde {off} en handle {handle}")
            await asyncio.sleep(0.03)

        if attempts >= 50:
            print('\033[94m' + f"(ATTEMPS-LIMITs) Reading directly: attempts >= 50. handle={handle}, off={off}, size={size}" + '\033[0m')
            return await item.data.structure_item.content.read_func(handle, off, size);

        self.bufferArray[handle].seek(off)
        
        #print(f"(Buffer) Reading from buffer: handle={handle}, off={off}, size={size}")
        return self.bufferArray[handle].read(size)

    def memoryWrite(self, handle, off, size, data):
        if handle not in self.bufferArray:
            print("(Buffer) Error: handle not found")
            return
        if len(data) != size:
            print("(Buffer)  Error: size of data does not match the specified size")
            print(f"(Buffer) len(data) = {len(data)}, size = {size}")
            return
        self.bufferArray[handle][off:off + size] = data
        self.markAsWritten(handle, off, size)

    def markAsWritten(self, handle, off, size):
        self.writtenRanges[handle].add((off, off + size))

    def hasBeenWritten(self, handle, off, size):
        if handle not in self.writtenRanges:
            return False
        
        target_start = off
        target_end = off + size
        
        sorted_ranges = sorted(self.writtenRanges[handle])
        
        for start, end in sorted_ranges:
            if start <= target_start and end >= target_start:
                target_start = end
            
            if target_start >= target_end:
                return True
            
            if start > target_end:
                break
        
        return False
    
    async def bufferNextBytes(self, handle, offset, readFunc, total_size, readSize):
        print(f"Llamado a bufferNextBytes, arguments (handle={handle}, offset={offset}, readFunc={readFunc}, total_size={total_size}, readSize={readSize})")

        if handle not in self.bufferArray:
            print("(Buffer) Error: handle not found")
            return False

        if handle not in self.bufferingTasks:
            self.bufferingTasks[handle] = []

        target_start = offset
        target_end = offset + readSize

        is_covered = False

        sorted_tasks = sorted(self.bufferingTasks[handle], key=lambda x: x['start_offset'])

        for task in sorted_tasks:
            if task['start_offset'] <= target_start and task['end_offset'] >= target_start:
                target_start = task['end_offset']

            if target_start >= target_end:
                is_covered = True
                break

        if not is_covered:
            BUFFER_MB = 50
            chunk_size = 3000000  # 1.5MB
            num_tasks = 2;

            new_task = {
                'start_offset': offset,
                'end_offset': min(offset + BUFFER_MB * 1024 * 1024, total_size)
            }

            self.bufferingTasks[handle].append(new_task)

            async def read_and_write_sub_chunk(start, end):
                nonlocal handle, readFunc
                data = await readFunc(handle, start, end - start)
                self.memoryWrite(handle, start, end - start, data)
                print(f"(Buffer) Writed (handle={handle}, off={start}, size={end - start})")

            current_offset = offset
            while current_offset < new_task['end_offset']:
                next_chunk_size = min(chunk_size, new_task['end_offset'] - current_offset, total_size - current_offset)
                
                # Dividir el tamaño del chunk entre el número de tareas
                sub_chunk_size = next_chunk_size // num_tasks

                # Crear y lanzar las tareas
                tasks = [
                    read_and_write_sub_chunk(current_offset + i * sub_chunk_size, current_offset + (i + 1) * sub_chunk_size)
                    for i in range(num_tasks)
                ]
                
                # Esperar a que todas las tareas se completen antes de continuar
                await asyncio.gather(*tasks)

                current_offset += next_chunk_size

            self.bufferingTasks[handle].remove(new_task)

            print("Buffer filled.")
            return True

class FileSystemOperations(pyfuse3.Operations, FileSystemOperationsMixin):
    FsRegistryItem = RegistryItem[FileSystemItem] | RegistryRoot[FileSystemItem]
    logger = logger.getChild(f"FileSystemOperations")

    def __init__(
        self,
        root: vfs.DirLike,
    ):
        super(FileSystemOperations, self).__init__()
        self._root = root

        """ Locks while updating """
        self._update_lock = MyLock(
            "FileSystemOperations.update_lock", logger=self.logger
        )
        
        self.memory_buffer = MemoryBuffer()
        self.thread_dict = {}
        self.queue_dict = {}
        
        self._init()

    def _init(self):
        self._init_root(self._root)
        self._init_handles()

    def _init_root(self, root: vfs.DirLike, last_inode=None):
        self.logger.debug(f"init_root")

        self._inodes = InodesRegistry[FileSystemItem](
            self.create_FileSystemItem(
                root,
                self._create_attributes_for_item(root, InodesRegistry.ROOT_INODE),
            ),
            last_inode=last_inode,
        )

    def _init_handles(self, last_fh=None):
        self._handles = FileSystemHandles[InodesRegistryItem](last_fh=last_fh)

    @overload
    def _str_to_bytes(self, s: str) -> bytes:
        ...

    @overload
    def _str_to_bytes(self, s: list[str]) -> list[bytes]:
        ...

    def _str_to_bytes(self, s: str | list[str]) -> bytes | list[bytes]:
        if isinstance(s, list):
            return list(map(self._str_to_bytes, s))

        return s.encode("utf-8")

    def _bytes_to_str(self, bs: bytes) -> str:
        return bs.decode("utf-8")

    @property
    def handles(self):
        return self._handles

    @property
    def inodes(self) -> InodesRegistry[FileSystemItem]:
        return self._inodes

    @property
    def vfs_root(self) -> vfs.VfsRoot:
        return self._root

    def create_FileSystemItem(
        self,
        structure_item: vfs.DirContentItem,
        attrs: pyfuse3.EntryAttributes,
    ):
        return FileSystemItem(structure_item, attrs)

    def _create_attributes_for_item(
        self,
        item: vfs.DirContentItem,
        inode: int | None,
    ):
        if isinstance(item, vfs.DirLike):
            return create_directory_attributes(
                inode,
                stamp=int(item.creation_time.timestamp() * 1e9),
            )
        else:
            return create_file_attributes(
                size=item.content.size,
                stamp=int(item.creation_time.timestamp() * 1e9),
            )

    def update_subitem(
        self, path: str, new_item: vfs.DirContentItem, parent_inode: int
    ):
        self.logger.debug(
            f"update_subitem: {new_item.name}, parent_inode={parent_inode} ({self.inodes.get_item_path(parent_inode)})"
        )

        # old_fs_item = self.inodes.get_child_item_by_name(new_item.name, parent_inode)
        old_fs_item = self.inodes.get_by_path(path)

        if old_fs_item is None:
            self.logger.debug(f"update_subitem: {path} is not in inodes. Adding.")

            self.add_subitem(new_item, parent_inode)
            return

        self.logger.debug(f"update_subitem: old={old_fs_item}")

        if self._bytes_to_str(old_fs_item.name) != new_item.name:
            self.logger.debug(f"update_subitem: item renamed")
            pyfuse3.invalidate_entry_async(parent_inode, old_fs_item.name)

        try:
            pyfuse3.invalidate_inode(old_fs_item.inode)
        except FileNotFoundError as e:
            self.logger.error(
                f"Error invalidating inode {old_fs_item.inode} ({old_fs_item.data.structure_item.name}). {e.strerror}"
            )

        fs_item = self.create_FileSystemItem(
            new_item,
            self._create_attributes_for_item(new_item, inode=0),
        )

        item = self.inodes.add_item_to_inodes(
            name=self._str_to_bytes(new_item.name),
            data=fs_item,
            parent_inode=parent_inode,
            inode=old_fs_item.inode,
        )

        item.data.attrs.st_ino = item.inode
        item.data.attrs.st_ctime_ns = old_fs_item.data.attrs.st_ctime_ns
        item.data.attrs.st_mtime_ns = int(datetime.now().timestamp() * 1e9)

        return item

    def add_subitem(self, vfs_item: vfs.DirContentItem, parent_inode: int):
        self.logger.debug(
            f"add_subitem: {vfs_item.name}, parent_inode={parent_inode} ({self.inodes.get_item_path(parent_inode)})"
        )

        fs_item = self.create_FileSystemItem(
            vfs_item,
            self._create_attributes_for_item(vfs_item, inode=0),
        )

        item = self.inodes.add_item_to_inodes(
            name=self._str_to_bytes(vfs_item.name),
            data=fs_item,
            parent_inode=parent_inode,
        )

        item.data.attrs.st_ino = item.inode

        return item

    def remove_subitem(self, parent_inode: int, name: str | bytes):
        if isinstance(name, str):
            name = self._str_to_bytes(name)

        item = self.inodes.get_child_item_by_name(name, parent_inode)

        if item is not None:
            self.inodes.remove_item_with_children(item.inode)

    @exception_handler
    async def getattr(self, inode: int, ctx=None):
        item = self._inodes.get_item_by_inode(inode)

        if item is None:
            self.logger.error(f"= getattr({inode}): missing in inodes registry")
            raise pyfuse3.FUSEError(errno.ENOENT)

        self.logger.debug(f"getattr({inode}) = {item.name}")

        self.logger.debug(f"= getattr({inode},)\t{item.data.structure_item.name}")

        return item.data.attrs

    # @measure_time(logger_func=measure_time_logger.debug)
    @exception_handler
    async def _read_dir_content(self, parent_item: InodesRegistryItem):
        self.logger.debug(f"_read_dir_content {parent_item.name}")
        async with self._update_lock:
            handle = None
            structure_item = parent_item.data.structure_item

            if not isinstance(structure_item, vfs.DirLike):
                self.logger.error("_read_content(): parent_item is not DirLike")
                raise pyfuse3.FUSEError(errno.ENOENT)

            handle = await structure_item.content.opendir_func()
            res = []

            for child_item in await structure_item.content.readdir_func(handle, 0):
                item = self.add_subitem(child_item, parent_item.inode)
                res.append(item)

            await structure_item.content.releasedir_func(handle)

        return res

    # @measure_time(logger_func=measure_time_logger.debug)
    @exception_handler
    async def lookup(
        self, parent_inode: int, name: bytes, ctx=None
    ) -> pyfuse3.EntryAttributes:
        # Calls to lookup acquire a read-lock on the inode of the parent directory (meaning that lookups in the same
        #         directory may run concurrently, but never at the same time as e.g. a rename or mkdir operation).

        self.logger.debug(f"= lookup({parent_inode}, {name})")

        parent_item = self._inodes.get_item_by_inode(parent_inode)

        if parent_item is None:
            self.logger.error(
                f"lookup({parent_inode}): missing parent_inode={parent_inode}"
            )
            raise pyfuse3.FUSEError(errno.ENOENT)

        self.logger.debug(f"lookup(): parent_item={parent_item.name}")

        if not vfs.DirLike.guard(parent_item.data.structure_item):
            self.logger.error("lookup(): parent_item is not DirLike")
            raise pyfuse3.FUSEError(errno.ENOENT)

        # child_inodes = self._inodes.get_items_by_parent(parent_inode)

        if not self._inodes.was_content_read(parent_item.inode):
            await self._read_dir_content(parent_item)
            self._inodes.set_content_read(parent_item.inode)

        item = self._inodes.get_child_item_by_name(name, parent_inode)

        if item is None:
            self.logger.debug(
                f"lookup(parent_inode={parent_inode},name={name}): not found"
            )
            raise pyfuse3.FUSEError(errno.ENOENT)

        self.logger.debug(f"lookup(): returning {item}")

        return item.data.attrs

    @exception_handler
    async def forget(self, inode_list):
        self.logger.debug(f"= forget({inode_list}")

    # @measure_time(logger_func=measure_time_logger.debug)
    @exception_handler
    async def opendir(self, inode: int, ctx):
        self.logger.debug(f"= opendir({inode})")

        item = self._inodes.get_item_by_inode(inode)

        if item is None:
            self.logger.error(
                f"opendir({inode}): missing item. inodes: {list(self._inodes._inodes.keys())}"
            )
            raise pyfuse3.FUSEError(errno.EBADF)

        self.logger.debug(f"= opendir({inode}) {item.data.structure_item.name}")

        if not vfs.DirLike.guard(item.data.structure_item):
            self.logger.error(f"opendir({inode}): structure_item is not DirLike")
            raise pyfuse3.FUSEError(errno.ENOTDIR)

        path = self._inodes.get_item_path(item.inode)

        if path is not None:
            vfs_path = InodesRegistry.join_path(path)

            if vfs_path is None:
                self.logger.error("opendir(): missing vfs_path")
                raise pyfuse3.FUSEError(errno.ENOENT)

            self.logger.debug(f"opendir(): vfs_path = {vfs_path}")

        handle = await item.data.structure_item.content.opendir_func()

        fh = self._handles.open_fh(item, handle)

        self.logger.debug(f"= opendir({inode}) = {fh}")
        return fh

    # @measure_time(logger_func=measure_time_logger.debug)
    @exception_handler
    async def readdir(self, fh, off, token: pyfuse3.ReaddirToken):
        dir_item, handle = self._handles.get_by_fh(fh)

        if dir_item is None:
            self.logger.error("= readdir(fh={fh}, off={off}): missing dir_item")
            raise pyfuse3.FUSEError()

        self.logger.debug(f"= readdir({dir_item.name}, fh={fh}, off={off})")

        if isinstance(dir_item, vfs.DirLike):
            self.logger.error("= readdir(fh={fh}, off={off}): dir_item is not a folder")
            raise pyfuse3.FUSEError(errno.ENOTDIR)

        content = self._inodes.get_items_by_parent(dir_item)

        if content is None:
            self.logger.error(
                "= readdir(fh={fh}, off={off}): dir_item is not registered  in inodes"
            )
            raise pyfuse3.FUSEError(errno.ENOENT)

        # XXX
        if not self._inodes.was_content_read(dir_item.inode):
            content = await self._read_dir_content(dir_item)
            self._inodes.set_content_read(dir_item.inode)

        content = content[off:]

        for idx, sub_item in enumerate(content, off):
            resp = pyfuse3.readdir_reply(
                token,
                str.encode(sub_item.data.structure_item.name),
                sub_item.data.attrs,
                idx + 1,
            )

            if resp is False:
                break

    @exception_handler
    async def releasedir(self, fh):
        """If the directory was removed at this poing."""
        item, handle = self._handles.get_by_fh(fh)

        if item is None:
            self.logger.debug(
                f"releasedir(): missing {fh} in open handles. Probably the directory was removed."
            )
            return

        self.logger.debug(f"= releasedir({item.name}, {fh})")

        if item is None:
            self.logger.error(f"releasedir(): missing item with handle {fh}")
            raise pyfuse3.FUSEError(errno.ENOENT)

        if not vfs.DirLike.guard(item.data.structure_item):
            self.logger.error(f"releasedir(): item is not a folder {item}")
            raise pyfuse3.FUSEError()

        await item.data.structure_item.content.releasedir_func(handle)

        self._handles.release_fh(fh)
        self.logger.debug("= releasedir(): ok")

    @measure_time(logger_func=logger.debug)
    @exception_handler
    async def open(self, inode, flags, ctx):
        handle = None

        item = self._inodes.get_item_by_inode(inode)
        
        if item is None:
            self.logger.error(f"open({inode}) missing inode")
            raise pyfuse3.FUSEError(errno.ENOENT)

        if not vfs.FileLike.guard(item.data.structure_item):
            self.logger.error(f"open({inode}): is not file")
            raise pyfuse3.FUSEError(errno.EIO)

        # parent_dir.data.structure_item.writable
        self.logger.debug(
            f"= open({inode}, flags={flags_to_str(flags)}) = {item.data.structure_item.name}"
        )

        if flags & os.O_RDWR or flags & os.O_WRONLY:
            self.logger.error("open(): readonly")
            raise pyfuse3.FUSEError(errno.EPERM)

        handle = await item.data.structure_item.content.open_func()
        
        fh = self._handles.open_fh(item, handle)

        self.logger.debug(
            f"- done open({inode}): fh={fh}, name={item.data.structure_item.name}"
        )
        
        print(f"(operations.py) Storing at buffer: fh={fh}, size={item.data.structure_item.content.size}...")
        self.memory_buffer.storeFile(fh, item.data.structure_item.content.size)
        print(f"(operations.py) Stored at buffer: fh={fh}, size={item.data.structure_item.content.size}")
        
        print(f"(operations.py) open(inode={inode},flags={flags},fh={fh})")

        return pyfuse3.FileInfo(fh=fh)

    @measure_time(logger_func=logger.debug)
    @exception_handler
    async def read(self, fh, off, size):
        #self.logger.debug(f"= read(fh={fh},off={off},size={size}).")

        item, handle = self._handles.get_by_fh(fh)

        if item is None:
            self.logger.error(f"read(fh={fh}): missing item in open handles")
            raise pyfuse3.FUSEError(errno.ENOENT)

        if not vfs.FileLike.guard(item.data.structure_item):
            self.logger.error(f"read(fh={fh}): is not file.")
            raise pyfuse3.FUSEError(errno.EIO)        

        if fh not in self.thread_dict:
            print(f"(operations.py) Creando hilo para fh={fh}")
            loop = asyncio.get_event_loop()
            self.queue_dict[fh] = queue.Queue()
            self.thread_dict[fh] = threading.Thread(target=self.thread_target, args=(loop, fh))
            self.thread_dict[fh].start()
        
        self.queue_dict[fh].put((off, size, item))
        
        chunk = await self.memory_buffer.memoryRead(fh, off, size, item)
        #print('\033[92m' + f"(operations.py) read(handle={fh},off={off},size={size})" + '\033[0m')
        
        # output empty chunk
        #chunk = b''

        return chunk
    
    def thread_target(self, loop, fh):
        off, size, item = self.queue_dict[fh].get()
        
        future = asyncio.run_coroutine_threadsafe(
            self.memory_buffer.bufferNextBytes(fh, off, item.data.structure_item.content.read_func, item.data.structure_item.content.size, size), 
            loop
        )
        
        try:
            completed = future.result(timeout=1000)
            if completed:
                print(f"(thread_target) La tarea de buffering se ha completado fh = {fh}")
            else:
                print(f"(thread_target) La tarea de buffering no se ha completado fh = {fh}")
        except TimeoutError:
            print(f"(thread_target) La tarea de buffering ha excedido el tiempo de espera fh = {fh}")
            
        del self.thread_dict[fh]
        del self.queue_dict[fh]
        print(f"(thread_target) Hilo terminado fh = {fh}")

            
    @exception_handler
    async def release(self, fh):
        self.logger.debug(f"= release({fh})")
        item, data = self._handles.get_by_fh(fh)

        if item is None:
            self.logger.error(f"release(fh={fh}): missing item in open handles")
            return

        if not vfs.FileLike.guard(
            item.data.structure_item,
        ):
            self.logger.error(f"release({fh}): is not file")
            raise pyfuse3.FUSEError(errno.EIO)

        await item.data.structure_item.content.close_func(data)

        self._handles.release_fh(fh)

    # async def forget(self, inode_list):
    #     pass
