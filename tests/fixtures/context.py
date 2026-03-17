from dataclasses import dataclass, field


@dataclass
class Context:
    called_tools: list[str] = field(default_factory=list)
    cache: dict[str, str] = field(default_factory=dict)
    request_count: int = 0
    notes: dict[str, list[str]] = field(default_factory=dict)

    def get_called_tools(self) -> list[str]:
        return self.called_tools

    def add_called_tool(self, tool_name: str) -> None:
        self.called_tools.append(tool_name)

    def clear(self) -> None:
        self.called_tools = []

    def increment_request_count(self) -> int:
        self.request_count += 1
        return self.request_count

    def get_request_count(self) -> int:
        return self.request_count

    def set_cache(self, key: str, value: str) -> None:
        self.cache[key] = value

    def get_cache(self, key: str) -> str | None:
        return self.cache.get(key)

    def add_note(self, topic: str, note: str) -> None:
        self.notes.setdefault(topic, []).append(note)

    def get_notes(self, topic: str) -> list[str]:
        return self.notes.get(topic, [])
