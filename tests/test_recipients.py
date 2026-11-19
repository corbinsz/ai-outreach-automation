"""The To field stays blank on a live scrape and is filled only for samples."""

from src.recipients import suggested_recipient


def test_live_mode_does_not_choose_a_recipient():
    assert suggested_recipient(["hello@northwind.example"], demo_mode=False) == ""
    assert suggested_recipient([], demo_mode=False) == ""


def test_demo_mode_prefills_the_first_sample_address():
    assert (
        suggested_recipient(["hello@northwind.example", "other@northwind.example"], demo_mode=True)
        == "hello@northwind.example"
    )
    assert suggested_recipient(["  "], demo_mode=True) == ""
