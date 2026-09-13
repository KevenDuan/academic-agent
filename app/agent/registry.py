from __future__ import annotations

import importlib.util
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import yaml


@dataclass(frozen=True)
class SkillContext:
    rag_engine: Any
    translator: Any


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], SkillContext], str]

    def to_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class SkillRegistry:
    """Load self-describing skills from folders without changing the agent core."""

    def __init__(self, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir).expanduser().resolve()
        self.skills: dict[str, Skill] = {}
        self.load()

    def load(self) -> list[Skill]:
        loaded: dict[str, Skill] = {}
        if self.skills_dir.exists():
            for folder in sorted(self.skills_dir.iterdir()):
                if not folder.is_dir():
                    continue
                skill = self._load_folder(folder)
                if skill is not None:
                    if skill.name in loaded:
                        raise ValueError(f"重复的技能名称：{skill.name}")
                    loaded[skill.name] = skill
        self.skills = loaded
        return list(loaded.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [skill.to_tool_schema() for skill in self.skills.values()]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: SkillContext,
    ) -> str:
        skill = self.skills.get(name)
        if skill is None:
            raise KeyError(f"未注册的技能：{name}")
        return str(skill.run(arguments, context))

    @staticmethod
    def _load_folder(folder: Path) -> Skill | None:
        metadata_path = folder / "SKILL.md"
        implementation_path = folder / "skill.py"
        if not metadata_path.exists() or not implementation_path.exists():
            return None
        metadata = SkillRegistry._parse_metadata(metadata_path)
        name = str(metadata.get("name") or folder.name).strip()
        description = str(metadata.get("description") or "").strip()
        parameters = metadata.get("parameters") or {"type": "object", "properties": {}}
        module = SkillRegistry._import_module(implementation_path)
        run = getattr(module, "run", None)
        if not callable(run):
            raise ValueError(f"技能缺少 run(args, context)：{implementation_path}")
        return Skill(name, description, parameters, run)

    @staticmethod
    def _parse_metadata(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"SKILL.md 缺少 YAML front matter：{path}")
        _, front_matter, _body = text.split("---", 2)
        metadata = yaml.safe_load(front_matter) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"SKILL.md 元数据必须是对象：{path}")
        return metadata

    @staticmethod
    def _import_module(path: Path) -> ModuleType:
        module_name = f"academic_agent_skill_{path.stem}_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载技能：{path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
