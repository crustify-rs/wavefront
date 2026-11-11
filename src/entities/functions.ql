/**
 * Enumerate every Function entity in the database.
 *
 * Returns one row per Function, regardless of whether the body is in
 * the database. Declaration-only externs (libc, assembly-displaced
 * functions, partial-extraction targets) appear in the result set
 * with `def_file = ""` — consumers must distinguish them from
 * functions whose body is in the DB.
 *
 * Linkage class is derived from the function's properties:
 *   - "function_inline_header"  — declared inline AND defined in .h
 *   - "function_inline_tu"      — declared inline AND defined in .c (or .cpp)
 *   - "function_static"         — file-local linkage (declared `static`)
 *   - "function_exported"       — externally linkable (the default)
 *
 * # cols:
 *   name        : the function's C identifier
 *   linkage     : one of the four classes above
 *   def_file    : repository-relative path of the definition's file,
 *                 or "" if no definition is in the DB
 *   decl_files  : pipe-separated list of repository-relative paths
 *                 of all declaration entries (typically headers); may
 *                 be empty if no declaration entries are recorded
 *   signature   : full C signature string, e.g.
 *                 `int foo(const char *, size_t)`
 *   loc         : body line span (endLine - startLine + 1) of the definition,
 *                 or 0 for a declaration-only function (no body in the DB).
 *                 Consumed by the port bin-packer's lines-of-code budget.
 *   is_variadic : "1" if the function takes a trailing `...` (a C variadic
 *                 like `printf`), "0" otherwise. A variadic has no safe Rust
 *                 signature — `extern "C"` variadics are unstable and the
 *                 wrapper must instead bind the `v*`-suffixed `va_list`
 *                 sibling or emit a fixed-arity shim — so the wrap/port
 *                 stages need this off the signature, which the `signature`
 *                 column's parameter list alone does not reveal.
 *
 *   declaring_type / declaring_type_def_file: the C++ member's owning type.
 *   member_kind : "constructor", "destructor", "method", or empty.
 *
 * No `hasDefinition()` filter here — consumers need declaration-only
 * functions to identify boundary-crossing externs. The def_file ""
 * sentinel surfaces the missing-body case explicitly.
 */
import cpp
import identity

string linkageClassOf(Function fn) {
  if fn.isInline() and exists(fn.getDefinition()) and
     fn.getDefinition().getFile().getExtension() = ["h", "hh", "hpp", "hxx"]
  then result = "function_inline_header"
  else if fn.isInline() and exists(fn.getDefinition()) and
          not fn.getDefinition().getFile().getExtension() = ["h", "hh", "hpp", "hxx"]
  then result = "function_inline_tu"
  else if fn.isStatic()
  then result = "function_static"
  else result = "function_exported"
}

string definitionFileOf(Function fn) {
  if exists(fn.getDefinition())
  then result = pathOf(fn.getDefinition().getFile())
  else result = ""
}

string declFilesOf(Function fn) {
  result = concat(File h |
    h = fn.getADeclarationEntry().getFile()
  | pathOf(h), "|"
    order by pathOf(h)
  )
}

string signatureOf(Function fn) {
  if functionNameOf(fn) != fn.getName()
  then result = fn.getType().toString() + " " + functionNameOf(fn)
  else
    result = fn.getType().toString() + " " + fn.getName() + "(" +
      concat(int i | exists(fn.getParameter(i)) |
        fn.getParameter(i).getType().toString(), ", " order by i
      ) + ")"
}

string declaringTypeOf(Function fn) {
  if exists(fn.getDeclaringType())
  then result = canonicalTypeName(fn.getDeclaringType())
  else result = ""
}

string declaringTypeFileOf(Function fn) {
  if exists(fn.getDeclaringType())
  then result = defFileOf(fn.getDeclaringType())
  else result = ""
}

string memberKindOf(Function fn) {
  if fn instanceof Constructor then result = "constructor"
  else if fn instanceof Destructor then result = "destructor"
  else if fn instanceof MemberFunction then result = "method"
  else result = ""
}

/**
 * Body line span of the function's definition (endLine - startLine + 1), or 0
 * when no body is in the DB (declaration-only extern). Uses the definition's
 * block location so the span reflects the implementation, not the signature.
 */
int locOf(Function fn) {
  if exists(fn.getBlock())
  then
    result =
      fn.getBlock().getLocation().getEndLine() -
        fn.getBlock().getLocation().getStartLine() + 1
  else result = 0
}

/**
 * 1 when the function takes a trailing `...`, else 0. A helper predicate
 * rather than an inline `if` — the select clause takes terms, not expressions.
 */
int isVariadicOf(Function fn) {
  if fn.isVarargs() then result = 1 else result = 0
}

from Function fn
select functionNameOf(fn) as name,
       linkageClassOf(fn) as linkage,
       definitionFileOf(fn) as def_file,
       declFilesOf(fn) as decl_files,
       signatureOf(fn) as signature,
       locOf(fn) as loc,
       isVariadicOf(fn) as is_variadic,
       declaringTypeOf(fn) as declaring_type,
       declaringTypeFileOf(fn) as declaring_type_def_file,
       memberKindOf(fn) as member_kind
