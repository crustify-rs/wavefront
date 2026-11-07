/**
 * Enumerate every user-defined type referenced from a global
 * variable's declared type.
 *
 * One row per (global, user_type) pair. Field-level analogue of
 * `edges/signature_type_uses.ql` and `edges/field_type_uses.ql` —
 * for each global variable in the database, walk its declared type
 * and emit a row for each user-defined type reached.
 *
 * Why this exists: a port-reachable wrap global whose type is
 * `SSL_METHOD *` (or `struct ssl_method_st *`) pulls `SSL_METHOD`
 * onto the boundary, even when no port-fn signature or body
 * mentions `SSL_METHOD` directly. The composer joins this query
 * against port-side `global_accesses` rows to close the gap.
 *
 * Both typedef aliases and their underlying user-types appear as
 * separate rows along the chain — same convention as the other
 * `*_type_uses.ql` queries.
 *
 * # cols:
 *   global_name      : the variable's C identifier
 *   global_def_file  : repository-relative path of the global's
 *                      definition site, or "" if no definition is
 *                      in the DB (declaration-only externs)
 *   type_name        : the user-defined type's C tag
 *   type_kind        : "struct" | "union" | "enum" | "typedef"
 *   type_def_file    : repository-relative path of the type's
 *                      definition site, or "" if no full-body
 *                      definition is in the DB
 *
 * Consumer: `src/compose/types_manifest.py` — global-
 * driven reachability gate (scenario 7 in the reach ruleset).
 *
 * Function-local variables and parameters are NOT enumerated here —
 * local-variable type uses are covered by `local_type_uses.ql`
 * keyed on the enclosing function. This query is GlobalVariable-
 * scoped only.
 */
import cpp
import identity

string defFileOf(Variable g) { result = globalDefFile(g) }

string typeDefFileOf(UserType t) {
  exists(UserType c | c = canonicalUserType(t) |
    if exists(c.getDefinition())
    then result = pathOf(c.getDefinition().getFile())
    else result = ""
  )
}


from Variable g, UserType t
where
  isGlobalEntity(g) and
  reachableUserType(g.getType(), t) and
  t.getName() != "" and
  not t.getName().prefix(1) = "(" and
  typeKindOf(t) != "other"
select globalName(g) as global_name,
       defFileOf(g) as global_def_file,
       cppName(t) as type_name,
       typeKindOf(t) as type_kind,
       typeDefFileOf(t) as type_def_file
