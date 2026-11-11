"""Check the demo's public CLI output against the C++ source relationships."""

import json
from pathlib import Path
import sys


def verify(output: Path) -> None:
    types = {
        record["composed"]["name"]: record["composed"]
        for record in json.loads((output / "types.json").read_text())
    }
    symbols = {
        record["composed"]["name"]: record
        for record in json.loads((output / "symbols.json").read_text())
    }
    point = "geometry::Point"
    rectangle = "geometry::Rectangle"
    constructor = "geometry::Rectangle::Rectangle(geometry::Point, geometry::Point)"
    destructor = "geometry::Rectangle::~Rectangle()"
    area = "geometry::Rectangle::area() const"
    scaled_area = "geometry::Rectangle::area(double) const"
    caller = "geometry::calculate_area(geometry::Point, geometry::Point, double)"

    assert types[point]["kind"] == "struct"
    assert types[rectangle]["kind"] == "class"
    assert types[rectangle]["defined_in"] == "geometry.hpp"
    assert {field["name"] for field in types[rectangle]["fields"]} == {"lower_", "upper_"}
    for name, kind in ((constructor, "constructor"), (destructor, "destructor"),
                       (area, "method"), (scaled_area, "method")):
        symbol = symbols[name]
        assert symbol["composed"]["member_kind"] == kind, name
        assert symbol["composed"]["declaring_type"] == {
            "name": rectangle, "defined_in": "geometry.hpp",
        }, name
        assert symbol["findings"]["lifetime"] is None, name

    schedule = json.loads((output / "schedule.json").read_text())
    items = {
        item["name"]: item
        for wave in schedule["waves"] for batch in wave["batches"] for item in batch["items"]
    }
    for consumer, group, producers in (
        (rectangle, "types", {point}),
        (constructor, "types", {rectangle, point}),
        (destructor, "types", {rectangle}),
        (area, "types", {rectangle}),
        (scaled_area, "symbols", {area}),
        (caller, "symbols", {constructor, destructor, scaled_area}),
    ):
        dependencies = {dep["name"] for dep in items[consumer]["deps"][group]}
        assert producers <= dependencies, (consumer, producers - dependencies)
        assert all(items[producer]["layer"] < items[consumer]["layer"] for producer in producers)

    print("Verified C++ class, member identities, lifecycle calls, and dependency ordering.")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
