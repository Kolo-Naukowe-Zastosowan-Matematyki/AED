import json
from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5


def uid(key):
    return uuid5(NAMESPACE_URL, "urn:misja-aed:konkurs:" + key)


@lru_cache(maxsize=1)
def public_column_labels(schema_file):
    with open(schema_file, encoding="utf-8") as source:
        columns = json.load(source)["kolumny"]
    return {key: column["nazwa"].rstrip("?") for column in columns if not column["chroniona"]
            for key in (column["pole"], column["nazwa"])}
