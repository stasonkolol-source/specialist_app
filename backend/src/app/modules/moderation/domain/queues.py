"""Очереди модерации (ADR-0016 §4, ARCHITECTURE §14.2)."""

from enum import StrEnum
from typing import Final


class Queue(StrEnum):
    SAFETY = "safety"
    """P0: наркотики, вербовка, оружие, сексуальные услуги, угрозы, дети."""
    FRAUD = "fraud"
    """P1: «взял предоплату», фишинг, самозванцы; в MVP — и заявления третьих лиц и споры."""
    PREMOD = "premod"
    """P2: профили и портфолио новых, флаги классификаторов."""
    APPEALS = "appeals"
    """Апелляции (2.5b): решение пересматривает человек."""


PRIORITY: Final = (Queue.SAFETY, Queue.FRAUD, Queue.PREMOD, Queue.APPEALS)
"""Строже — раньше: кейс с двумя поводами живёт в более строгой очереди."""


def stricter(a: Queue, b: Queue) -> Queue:
    return a if PRIORITY.index(a) <= PRIORITY.index(b) else b


def dispute_queue(kind: str) -> Queue:
    """Очередь спора (6.1c): «ущерб, грубость или угрозы» — безопасность P0, остальные — P1
    (в MVP туда же, где мошенничество и заявления третьих лиц)."""
    return Queue.SAFETY if kind == "safety" else Queue.FRAUD
