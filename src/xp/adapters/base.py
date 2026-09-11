from __future__ import annotations

from abc import ABC, abstractmethod


class AdapterError(RuntimeError):
    pass


class CapabilityAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> set[str]:
        raise NotImplementedError
