"""Снимок справочника для тестов импорта: у теста его нет, сбрасывать нечего."""


class NoSnapshotCache:
    def invalidate(self) -> None:
        pass
