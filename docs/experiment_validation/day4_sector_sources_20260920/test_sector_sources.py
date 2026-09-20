import pytest

from inspect_sector_sources import inspect


def fixture():
    return b'''<pre class="announcementContent">Announcement for May 02, 2023 at 10:21 PM GMT
THIS IS AN ANNOUNCEMENT FOR THE MSCI GLOBAL STANDARD INDEXES
subject to change before implementation
Friday, March 17, 2023 in GICS Direct
effective June 01, 2023
May 31, 2023.
USA 2
VIETNAM 1

USA

EXAMPLE A
CURRENT GICS SUB-INDUSTRY 45102020 Example
NEW GICS SUB-INDUSTRY 40201060 Example

EXAMPLE B
CURRENT GICS SUB-INDUSTRY 60101040 Example
NEW GICS SUB-INDUSTRY 60104010 Example

VIETNAM
irrelevant data
</pre>'''


def test_effective_dates_and_scope_remain_separate():
    metadata, rows = inspect(fixture())
    assert metadata["announced_at_utc"] == "2023-05-02T22:21:00+00:00"
    assert metadata["msci_effective_date"] == "2023-06-01"
    assert metadata["separately_referenced_gics_direct_spdji_after_close_date"] == "2023-03-17"
    assert metadata["source_scope"] == "MSCI_GLOBAL_STANDARD_INDEXES"
    assert metadata["usa_sector_code_changes"] == 1
    assert metadata["sector_code_transition_counts"] == {"45->40": 1}
    assert len(rows) == 2
    assert not metadata["usable_as_s6_input"]
    assert metadata["certified_s6_rebalances"] == 0
    assert "ticker" not in rows[0] and "security_id" not in rows[0]


@pytest.mark.parametrize("old,new", [
    (b"USA 2", b"USA 3"),
    (b"EXAMPLE B", b"EXAMPLE A"),
    (b"45102020", b"4510202"),
    (b"Announcement for", b"Unknown timestamp"),
    (b"MSCI GLOBAL STANDARD INDEXES", b"S&P 500"),
    (b"subject to change before implementation", b"final"),
    (b"effective June 01, 2023", b"effective March 17, 2023"),
    (b"</pre>", b""),
    (b"NEW GICS SUB-INDUSTRY 60104010 Example", b""),
])
def test_incomplete_or_wrong_source_is_rejected(old, new):
    with pytest.raises(ValueError):
        inspect(fixture().replace(old, new))


def test_multiple_announcements_are_not_silently_merged():
    with pytest.raises(ValueError):
        inspect(fixture() + fixture())
