from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_SKILL_CANDIDATES = (
    "audio-alignment-audit",
    "hardcoded-config-audit",
    "pipeline-stage-contracts",
    "review-wizard-qa",
    "karaoke-style-library",
    "provenance-artifact-audit",
    "pap-ollama-audit",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _markdown_links(text: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def _documented_script_paths(markdown: str) -> list[Path]:
    matches = re.findall(r"`([^`]+\.ps1)`", markdown)
    paths: list[Path] = []
    for match in matches:
        normalized = match.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        paths.append(PROJECT_ROOT / normalized)
    return paths


class ProjectKnowledgeBaseTests(unittest.TestCase):
    def test_agent_workflow_scripts_exist(self) -> None:
        for name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                paths = _documented_script_paths(_read(PROJECT_ROOT / name))
                self.assertTrue(paths, f"{name} should document at least one workflow script")
                for path in paths:
                    self.assertTrue(path.exists(), f"Documented script path does not exist: {path}")

    def test_canonical_codex_pap_ollama_skill_has_required_files(self) -> None:
        skill_root = PROJECT_ROOT / ".Codex" / "skills" / "pap-ollama"
        required = (
            skill_root / "SKILL.md",
            skill_root / "scripts" / "run-ollama.ps1",
            skill_root / "scripts" / "select-model.ps1",
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing canonical Codex skill file: {path}")

        skill_text = _read(skill_root / "SKILL.md")
        self.assertIn(".Codex/tasks/context-contract.md", skill_text)
        self.assertIn(".Codex/tasks/current-prompt.md", skill_text)

    def test_hardcoded_config_audit_skill_is_active_and_actionable(self) -> None:
        skill_path = PROJECT_ROOT / ".Codex" / "skills" / "hardcoded-config-audit" / "SKILL.md"
        self.assertTrue(skill_path.exists(), f"Missing skill: {skill_path}")
        text = _read(skill_path)
        self.assertIn("name: hardcoded-config-audit", text)
        self.assertIn("description: Use when", text)
        for required_term in ("Evidence", "SDD", "tests", "hardcoded", "configuration"):
            with self.subTest(required_term=required_term):
                self.assertIn(required_term, text)

    def test_docs_landing_pages_exist(self) -> None:
        required = (
            PROJECT_ROOT / "docs" / "README.md",
            PROJECT_ROOT / "docs" / "architecture" / "README.md",
            PROJECT_ROOT / "docs" / "skills" / "README.md",
            PROJECT_ROOT / "docs" / "skills" / "gap-analysis.md",
            PROJECT_ROOT / "docs" / "skills" / "routing.md",
            PROJECT_ROOT / "docs" / "tasks" / "README.md",
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), f"Missing docs landing page: {path}")

    def test_docs_landing_page_links_resolve(self) -> None:
        docs = (
            PROJECT_ROOT / "docs" / "README.md",
            PROJECT_ROOT / "docs" / "architecture" / "README.md",
            PROJECT_ROOT / "docs" / "skills" / "README.md",
            PROJECT_ROOT / "docs" / "skills" / "gap-analysis.md",
            PROJECT_ROOT / "docs" / "skills" / "routing.md",
            PROJECT_ROOT / "docs" / "tasks" / "README.md",
        )
        for doc in docs:
            for link in _markdown_links(_read(doc)):
                if re.match(r"^[a-z]+://", link) or link.startswith("#"):
                    continue
                target = (doc.parent / link).resolve()
                with self.subTest(doc=doc, link=link):
                    self.assertTrue(target.exists(), f"Broken local markdown link: {doc} -> {link}")

    def test_skill_gap_analysis_documents_required_candidates(self) -> None:
        path = PROJECT_ROOT / "docs" / "skills" / "gap-analysis.md"
        text = _read(path)
        for candidate in REQUIRED_SKILL_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertIn(f"`{candidate}`", text)
        for required_heading in ("Evidence", "Priority", "Creation Criteria"):
            with self.subTest(required_heading=required_heading):
                self.assertIn(required_heading, text)

    def test_agents_links_to_skill_routing_contract(self) -> None:
        text = _read(PROJECT_ROOT / "AGENTS.md")
        self.assertIn("docs/skills/routing.md", text)
        self.assertIn("Skill Routing", text)

    def test_skill_routing_covers_every_gap_candidate(self) -> None:
        path = PROJECT_ROOT / "docs" / "skills" / "routing.md"
        text = _read(path)
        for candidate in REQUIRED_SKILL_CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertIn(f"`{candidate}`", text)
        for required_heading in ("Mandatory Routing", "Combination Order", "Do Not Use"):
            with self.subTest(required_heading=required_heading):
                self.assertIn(required_heading, text)

    def test_skill_docs_mark_hardcoded_config_audit_as_active(self) -> None:
        text = _read(PROJECT_ROOT / "docs" / "skills" / "README.md")
        self.assertIn("hardcoded-config-audit", text)
        self.assertIn("Active Project Skills", text)


if __name__ == "__main__":
    unittest.main()
