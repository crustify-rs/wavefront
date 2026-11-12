/**
 * What a macro's replacement list writes, for the queries that attribute a
 * reference to the macro whose `#define` writes it rather than to the code
 * that expands it (`edges/macro_references.ql`, `edges/enum_constant_uses.ql`).
 *
 * A `#define` is text, so what a name in it denotes is read off its
 * expansions in the traced build: an element an expansion produces that names
 * what the replacement list itself writes. An element an argument produces
 * keeps the argument's own location, inside the invocation, while one the
 * replacement lists produce, the macro's or a nested macro's, takes the
 * invocation's (`fromReplacementList`); and the name must be one the
 * replacement list writes, outside string and character literals, and not
 * one of the macro's parameters (`bodyIdentifier`), so that what a nested
 * macro writes is that macro's.
 */

import cpp

/** The parameter names of a function-like macro, from its head. */
string parameterOf(Macro m) {
  result = m.getHead().regexpCapture("[^(]*\\((.*)\\)", 1).splitAt(",").trim()
}

/**
 * An identifier the replacement list of `m` writes, outside string and
 * character literals, other than one of its parameters.
 */
string bodyIdentifier(Macro m) {
  result =
    m.getBody()
        .regexpReplaceAll("\"(\\\\.|[^\"\\\\])*\"|'(\\\\.|[^'\\\\])*'", " ")
        .regexpFind("[A-Za-z_][A-Za-z0-9_]*", _, _) and
  not result = parameterOf(m)
}

/**
 * `e`, expanded from `mi`, comes from a replacement list rather than from an
 * argument: it is located where the invocation is.
 */
predicate fromReplacementList(MacroInvocation mi, Locatable e) {
  e = mi.getAnExpandedElement() and
  exists(Location at, Location el | at = mi.getLocation() and el = e.getLocation() |
    el.getFile() = at.getFile() and
    el.getStartLine() = at.getStartLine() and
    el.getStartColumn() = at.getStartColumn() and
    el.getEndLine() = at.getEndLine() and
    el.getEndColumn() = at.getEndColumn()
  )
}
