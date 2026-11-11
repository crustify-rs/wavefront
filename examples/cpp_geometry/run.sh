#!/usr/bin/env bash
set -euo pipefail

example=$(cd -- "$(dirname -- "$0")" && pwd)
repo=$(cd -- "$example/../.." && pwd)
python=${PYTHON:-python3.13}
export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

mkdir -p "$example/.wavefront"
run=$(mktemp -d "$example/.wavefront/run.XXXXXX")
echo "Demo output: $run"
cp "$example"/{geometry.hpp,geometry.cpp,wavefront-config.json} "$run/"
cd "$run"
mkdir -p .wavefront/codeql
# The default traces the compiler. WAVEFRONT_BUILD_MODE=none extracts the
# sources without a build, for hosts where CodeQL cannot trace (Apple Silicon
# without Rosetta); both modes yield the same tables for this example.
case "${WAVEFRONT_BUILD_MODE:-trace}" in
none)
    codeql database create .wavefront/codeql/db --language=cpp --build-mode=none --source-root=.
    ;;
trace)
    codeql database create .wavefront/codeql/db --language=cpp --source-root=. \
        --command='g++ -std=c++17 -Wall -Wextra -Werror -c geometry.cpp -o .wavefront/geometry.o'
    ;;
*)
    echo "WAVEFRONT_BUILD_MODE must be 'trace' or 'none'" >&2
    exit 2
    ;;
esac

wf() { "$python" -m wavefront.cli "$run" --config wavefront-config.json "$@"; }
caller='geometry::calculate_area(geometry::Point, geometry::Point, double)'
wf extract-ql
wf query types --name geometry::Point geometry::Rectangle > types.json
wf query symbols --name 'geometry::Rectangle::Rectangle(geometry::Point, geometry::Point)' \
    'geometry::Rectangle::~Rectangle()' 'geometry::Rectangle::area() const' \
    'geometry::Rectangle::area(double) const' "$caller" > symbols.json
wf query dag --name "$caller" > dependencies.json
wf schedule --name "$caller" --transitive --output schedule.json
"$python" "$example/verify.py" "$run"
