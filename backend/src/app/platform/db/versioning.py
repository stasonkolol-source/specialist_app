"""Проверка версии при сохранении агрегата (ADR-0020 §5, уточнено в шаге 0.7b).

Identity map SQLAlchemy держит объекты по слабым ссылкам: репозиторий отдаёт доменный
объект, ORM-строку никто не держит, и сборщик мусора её удаляет. Тогда `session.get` в
`save` перечитывает строку уже с чужой версией, и без проверки правка молча перезатрёт
чужую. Поэтому `save` всегда сравнивает версию строки с версией агрегата, а гонку между
этой проверкой и UPDATE закрывает `version_id_col` ORM (WHERE version = …).
"""

from sqlalchemy.orm.exc import StaleDataError


def check_loaded_version(*, entity: str, loaded: int, expected: int) -> None:
    """Строку изменили после чтения агрегата — StaleDataError (UoW → 409, шаг 0.10)."""
    if loaded != expected:
        raise StaleDataError(f"{entity}: version {loaded} in database, {expected} expected")
