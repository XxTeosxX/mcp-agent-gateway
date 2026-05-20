from abc import ABC, abstractmethod


class UpstreamProvider(ABC):
    @abstractmethod
    async def get_valid_token(self, user_id: str) -> str: ...
