/**
 * Enumerate every direct mention of a user-defined type inside a
 * function BODY that ISN'T captured by the function's signature.
 *
 * The three forms a function can mention a type without exposing it
 * in its signature:
 *
 *   - `local_var` : a local variable declared with the type
 *                   (`SSL_CONNECTION *s;`, `EVP_MD_CTX ctx;`)
 *   - `cast`      : a C-style or static cast TO the type
 *                   (`(SSL *)p`, `(struct ssl_st *)x`)
 *   - `sizeof`    : a `sizeof(T)` expression where T is the type
 *
 * Signature uses (return type + parameter types) are handled by
 * edges/signature_type_uses.ql — this query covers the body-side
 * mentions the signature query misses. Together they enumerate
 * every function that "mentions" a type in any form, which is what
 * `opaque_in` minus `non_opaque_in` partitioning requires
 * (see `src/compose/types_manifest.py`).
 *
 * Pointer / array / qualifier wrapping is unwrapped to find the
 * underlying UserType — `T *x` records `T`, not the pointer type.
 * Typedef chains are followed because cpp-all's `TypedefType` is a
 * `DerivedType`, so the unwrap predicate descends through them and
 * surfaces the eventual struct/union/enum/typedef at the chain's
 * end. A function that mentions `SSL_CONNECTION` in a local
 * declaration therefore emits rows for both the typedef
 * `SSL_CONNECTION` and the underlying struct `ssl_connection_st`,
 * just as `signature_type_uses.ql` does — the consumer reconciles
 * via the type-index typedef walk.
 *
 * One row per occurrence — a function with three local
 * `SSL_CONNECTION *` declarations emits three local_var rows.
 * Consumers dedup by (function, type) when computing opaque-vs-
 * non-opaque partitioning.
 *
 * # cols:
 *   function_name      : enclosing function's C identifier
 *   function_def_file  : repository-relative path of the function's
 *                        definition site, or "" if no definition is
 *                        in the DB
 *   type_name          : the user-defined type's C tag
 *   type_kind          : "struct" | "union" | "enum" | "typedef"
 *   type_def_file      : repository-relative path of the type's
 *                        definition site, or "" if no full-body
 *                        definition is in the DB
 *   use_kind           : "local_var" | "cast" | "sizeof"
 *   use_line           : 1-indexed line number of the mention
 *
 * Consumer: types_manifest.py composer — joins with
 * signature_type_uses.ql + field_accesses.ql to populate
 * `opaque_in` on type manifest entries.
 *
 * No anonymous-tag filtering on the type (rows for
 * `(unnamed enum)`, `(unnamed class/struct/union)` are kept for
 * consistency with entities/types.ql; consumers can drop them).
 * `kindOf` "other" bucket is filtered — those are class-template /
 * non-C UserType subclasses that have no port/wrap analogue in
 * pure C codebases.
 */
import cpp
import identity

string fnDefFileOf(Function fn) { result = functionDefFile(fn) }

string typeDefFileOf(UserType t) {
  exists(UserType c | c = canonicalUserType(t) |
    if exists(c.getDefinition())
    then result = pathOf(c.getDefinition().getFile())
    else result = ""
  )
}

from Function body, Function fn, UserType t, string kind_str, int line_num
where
  fn = bodyOwner(body) and
  (
    // Local variable declared with this type.
    exists(LocalVariable lv |
      lv.getFunction() = body and
      reachableUserType(lv.getType(), t) and
      kind_str = "local_var" and
      line_num = lv.getLocation().getStartLine()
    )
    or
    // Cast TO this type.
    exists(Cast c |
      c.getEnclosingFunction() = body and
      reachableUserType(c.getType(), t) and
      kind_str = "cast" and
      line_num = c.getLocation().getStartLine()
    )
    or
    // sizeof(T) where T is the type.
    exists(SizeofTypeOperator s |
      s.getEnclosingFunction() = body and
      reachableUserType(s.getTypeOperand(), t) and
      kind_str = "sizeof" and
      line_num = s.getLocation().getStartLine()
    )
    or
    // C++: an object `new` allocates, which no local need name
    // (`return new Scene()`).
    exists(NewOrNewArrayExpr n |
      n.getEnclosingFunction() = body and
      reachableUserType(n.getAllocatedType(), t) and
      kind_str = "new" and
      line_num = n.getLocation().getStartLine()
    )
  ) and
  t.getName() != "" and
  typeKindOf(t) != "other"
select functionName(fn) as function_name,
       fnDefFileOf(fn) as function_def_file,
       cppName(t) as type_name,
       typeKindOf(t) as type_kind,
       typeDefFileOf(t) as type_def_file,
       kind_str as use_kind,
       line_num as use_line
