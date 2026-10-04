"""Набор примеров контент-правил — seeds/moderation/rule_examples.yaml (DEVELOPMENT_PLAN 2.4, 2.7b).

Им проверяют словарь двое: `cli seeds-validate` (entrypoints/seeds.py берёт отсюда модели
формата) и админка — прогон правки правила «у каких примеров поменяется вердикт» (2.7b). Файл
едет в образе вместе с остальными сидами (Dockerfile: `COPY seeds`) и читается раз на процесс.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.modules.moderation.domain.rules import RuleAction, RuleCategory, RuleExample

EXAMPLES_FILE = Path(__file__).resolve().parents[5] / "seeds" / "moderation" / "rule_examples.yaml"


class ExampleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    action: RuleAction | Literal["pass"]
    categories: list[RuleCategory] = Field(default_factory=list)

    def to_domain(self) -> RuleExample:
        return RuleExample(
            text=self.text,
            action=self.action if isinstance(self.action, RuleAction) else None,
            categories=frozenset(self.categories),
        )


class ExamplesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    examples: list[ExampleModel] = Field(min_length=1)


class YamlRuleExamples:
    def __init__(self, path: Path = EXAMPLES_FILE) -> None:
        self._path = path
        self._examples: tuple[RuleExample, ...] | None = None

    def load(self) -> tuple[RuleExample, ...]:
        if self._examples is None:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            parsed = ExamplesFile.model_validate(data)
            self._examples = tuple(example.to_domain() for example in parsed.examples)
        return self._examples
