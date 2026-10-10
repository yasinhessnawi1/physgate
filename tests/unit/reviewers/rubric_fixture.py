"""A placeholder rubric for the suite: the form a rubric must have, no domain content.

The real rubrics are researched and drafted elsewhere and promoted by a person;
nothing here stands in for their content.
"""

from __future__ import annotations

PLACEHOLDER = """# Placeholder review rubric

Used by the test suite only. It has the form a rubric must have and says nothing
about any domain.

## Verdict policy

A preamble section, as the real rubrics have.

## 1. Acceptance criteria

- **AC-1. The criterion is met.** Every acceptance criterion of the issued specification.

## 2. Domain standard violations

### A subheading

- **DS-1. A standard is broken.** A rule of the domain's standards file.
- **DS-2. Another standard is broken.** A second rule.

## 3. Skill-file antipatterns

- **AP-1. An antipattern is present.** One the skill file names.

## 4. Reward-hacking indicators

- **RH-1. Feature isolation.** A requirement met alone.
- **RH-2. Hard-coded values in place of computed ones.** A number written in.
- **RH-3. Disabled, skipped or weakened checks or tests.** A check switched off.
"""

#: The placeholder's item ids, by section.
PLACEHOLDER_IDS = ("AC-1", "DS-1", "DS-2", "AP-1", "RH-1", "RH-2", "RH-3")
