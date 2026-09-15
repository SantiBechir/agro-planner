class RecordingMessages:
    """Minimal messages-framework stand-in that records added messages."""

    def __init__(self):
        self.recorded = []

    def add(self, level, message, extra_tags=""):
        self.recorded.append((level, message))

    def __iter__(self):
        from django.contrib.messages.storage.base import Message
        return iter([Message(level, message) for level, message in self.recorded])

    def __len__(self):
        return len(self.recorded)

    def text(self):
        return " | ".join(str(message) for _, message in self.recorded)
