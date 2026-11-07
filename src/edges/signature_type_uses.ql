/**
 * Enumerate every user-defined type appearing in a function's
 * signature.
 *
 * One row per (function, type-tag-in-signature) pair. "Appearing in
 * the signature" means the tag is reachable by unwrapping pointers,
 * arrays, and const/volatile qualifiers from the function's return
 * type or any of its parameter types until a `UserType` (struct,
 * union, enum, typedef) is hit. Primitive types
 * (`int`, `char *`, `void *`, `size_t`, etc.) are skipped — they
 * aren't user-defined and don't carry boundary semantics.
 *
 * Each `(function, type)` pair appears at most once, even if the
 * same type appears in both the return and a parameter, or in
 * multiple parameters. The `position` column records the FIRST
 * position the type was found at, breaking ties:
 *
 *   - "return"
 *   - "param_<i>" for the i-th parameter (0-indexed)
 *
 * Typedefs unwrap one level — if the parameter type is
 * `SSL_SESSION *`, both the typedef `SSL_SESSION` AND its underlying
 * struct `ssl_session_st` appear as separate rows. Consumers
 * reconcile typedef ↔ struct identity at composition time using
 * entities/types.ql.
 *
 * # cols:
 *   function_name       : function's C identifier
 *   function_def_file   : repository-relative path of the function's
 *                         definition site, or "" if no definition is
 *                         in the DB
 *   type_name           : the user-defined type's C tag
 *   type_kind           : "struct" | "union" | "enum" | "typedef"
 *   type_def_file       : repository-relative path of the type's
 *                         definition site, or "" if no full-body
 *                         definition is in the DB
 *   position            : "return" | "param_<i>"
 *
 * No `hasDefinition()` filter on the function — declaration-only
 * externs still carry signature types worth recording (a wrap-side
 * function whose body is missing still has a type surface that may
 * pull in user-defined types).
 */
import cpp
import identity

string typeDefFileOf(UserType t) {
  exists(UserType c | c = canonicalUserType(t) |
    if exists(c.getDefinition())
    then result = pathOf(c.getDefinition().getFile())
    else result = ""
  )
}

string fnDefFileOf(Function fn) { result = functionDefFile(fn) }

from Function fn, UserType t, string pos
where
  isEntityFunction(fn) and
  (
    // Return type
    (reachableUserType(fn.getType(), t) and pos = "return")
    or
    // Parameter types
    exists(int i, Parameter p |
      p = fn.getParameter(i) and
      reachableUserType(p.getType(), t) and
      pos = "param_" + i.toString()
    )
  ) and
  // Skip anonymous tags (synthetic placeholder names like
  // `(unnamed enum)`) and the "other" UserType bucket. No `__`
  // prefix filter — compiler builtins are kept consistently with
  // entities/types.ql.
  t.getName() != "" and
  typeKindOf(t) != "other"
select functionName(fn) as function_name,
       fnDefFileOf(fn) as function_def_file,
       cppName(t) as type_name,
       typeKindOf(t) as type_kind,
       typeDefFileOf(t) as type_def_file,
       pos as position
