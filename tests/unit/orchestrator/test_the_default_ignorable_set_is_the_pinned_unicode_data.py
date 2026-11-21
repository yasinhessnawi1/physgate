"""The stream scans' Default_Ignorable_Code_Point set is the published one.

For the pinned interpreter's Unicode version, generated from the data file rather than typed.
"""

from __future__ import annotations

import unicodedata

from generate_default_ignorable import SOURCE_SHA256, UNICODE_VERSION, ranges, render

from physgate.orchestrator import default_ignorable


def test_the_set_is_for_the_unicode_version_the_interpreter_carries() -> None:
    assert default_ignorable.UNICODE_VERSION == UNICODE_VERSION == unicodedata.unidata_version
    assert default_ignorable.SOURCE_SHA256 == SOURCE_SHA256


def test_the_set_holds_the_source_s_total_and_its_known_members() -> None:
    found = default_ignorable.RANGES
    assert sum(hi - lo + 1 for lo, hi in found) == 4174  # the file's own "Total code points"
    assert all(a[1] < b[0] for a, b in zip(found, found[1:], strict=False))
    members = (0x00AD, 0x034F, 0x180E, 0x200D, 0x2060, 0x3164, 0xFE0F, 0xFEFF, 0xE0041, 0xE0100)
    assert all(any(lo <= cp <= hi for lo, hi in found) for cp in members)
    assert not any(lo <= 0x20 <= hi for lo, hi in found)


def test_the_generator_reads_the_published_line_format_and_writes_the_module() -> None:
    sample = (
        "# DerivedCoreProperties-15.0.0.txt\n"
        "00AD          ; Default_Ignorable_Code_Point # Cf       SOFT HYPHEN\n"
        "0041..005A    ; Uppercase # L&  [26] LATIN CAPITAL LETTER A..Z\n"
        "200B..200F    ; Default_Ignorable_Code_Point # Cf   [5] ZERO WIDTH SPACE..\n"
        "2060..2064    ; Default_Ignorable_Code_Point # Cf   [5] WORD JOINER..\n"
        "2065          ; Default_Ignorable_Code_Point # Cn       <reserved-2065>\n"
    )
    assert ranges(sample) == [(0xAD, 0xAD), (0x200B, 0x200F), (0x2060, 0x2065)]
    assert "(0x2060, 0x2065)," in render(ranges(sample))
