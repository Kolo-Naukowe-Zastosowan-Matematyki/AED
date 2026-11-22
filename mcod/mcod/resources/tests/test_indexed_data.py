import datetime

import pytest

from mcod.resources.indexed_data import prepare_item


@pytest.mark.parametrize(
    "value,type,output",
    [
        (
            datetime.datetime(2020, 2, 2, 0, 0),
            None,
            datetime.datetime(2020, 2, 2, 0, 0),
        ),
        (datetime.datetime(2020, 2, 2, 0, 0), "date", "2020-02-02"),
    ],
)
def test_prepare_item(value, type, output):
    assert prepare_item(value, type) == {"repr": output, "val": output}


@pytest.mark.parametrize("raw,expected", [("TRUE", True), ("FALSE", False), ("", None)])
def test_boolean_index_preserves_original_representation(raw, expected):
    assert prepare_item(raw, "boolean") == {"repr": raw or None, "val": expected}
