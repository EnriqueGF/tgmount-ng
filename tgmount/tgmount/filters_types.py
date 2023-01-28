from abc import abstractmethod
from typing import TypeVar, Protocol, Optional, Iterable, Callable

from tgmount.tgclient.message_types import MessageProto

from tgmount.tgmount.file_factory import FileFactoryBase, ClassifierBase
from tgmount.common.filter import FilterAllMessagesProto

T = TypeVar("T")
FilterConfigValue = str | dict[str, dict] | list[str | dict[str, dict]]


class FilterContext(Protocol):
    file_factory: FileFactoryBase
    classifier: ClassifierBase


class InstanceFromConfigProto(Protocol[T]):
    @staticmethod
    @abstractmethod
    def from_config(*args) -> Optional[T]:
        ...


class FilterFromConfigProto(InstanceFromConfigProto["FilterAllMessagesProto"]):
    @staticmethod
    @abstractmethod
    def from_config(*args) -> Optional["FilterAllMessagesProto"]:
        ...


FilterSingleMessage = Callable[[MessageProto], T | None | bool]
FilterAllMessages = FilterAllMessagesProto
Filter = FilterAllMessages
ParseFilter = Callable[[FilterConfigValue], list[Filter]]
