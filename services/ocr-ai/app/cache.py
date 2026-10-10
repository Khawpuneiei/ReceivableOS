"""Bounded, expiring process-local JSON caches. No raw pages or text persisted."""

import copy
import json
import time
from collections import OrderedDict
from threading import RLock


class JsonCache:
    def __init__(self, *, capacity=128, ttl=900, max_bytes=4 * 1024 * 1024):
        self.capacity, self.ttl, self.max_bytes = capacity, ttl, max_bytes
        self._entries = OrderedDict()
        self._bytes = 0
        self.lock = RLock()

    def _remove(self, key):
        _, _, size = self._entries.pop(key)
        self._bytes -= size

    def _expire(self):
        for key, (deadline, _, _) in list(self._entries.items()):
            if deadline <= time.monotonic():
                self._remove(key)

    def get(self, key):
        with self.lock:
            self._expire()
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(entry[1])

    def put(self, key, value):
        size = len(json.dumps(value, ensure_ascii=False).encode())
        if size > self.max_bytes:
            return
        with self.lock:
            self._expire()
            if key in self._entries:
                self._remove(key)
            while self._entries and (
                len(self._entries) >= self.capacity or self._bytes + size > self.max_bytes
            ):
                self._remove(next(iter(self._entries)))
            self._entries[key] = (time.monotonic() + self.ttl, copy.deepcopy(value), size)
            self._bytes += size
