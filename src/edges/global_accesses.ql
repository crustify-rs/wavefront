/**
 * Enumerate every access to a global variable.
 *
 * One row per `VariableAccess` whose target is a `GlobalVariable`.
 * Function-local variables and parameters are NOT enumerated —
 * those don't cross the wrap/port boundary by construction.
 *
 * The `access_kind` column unifies the three forms that produce a
 * cross-scope edge for globals:
 *
 *   - "write"  — the access is the lvalue of an assignment
 *                (`foo = 7;`, `foo += 1;`, `foo++;`)
 *   - "addr"   — the access is the operand of `&` (`&foo`)
 *   - "read"   — anything else (`if (foo == 5)`, `bar = foo`, etc.)
 *
 * All three are emitted as separate rows of this query; consumers
 * union them into `called_by.ref` for the global (the symbol
 * manifest does not split refs by kind) but the underlying kind is
 * available if a future consumer wants it.
 *
 * # cols:
 *   enclosing_name      : enclosing function's C identifier (or "" if
 *                         the access is at file scope, e.g. inside a
 *                         static initializer table)
 *   access_file         : repository-relative path of the access
 *                         site's file
 *   global_name         : the global variable's C identifier
 *   global_def_file     : repository-relative path of the global's
 *                         definition site, or "" if no definition is
 *                         in the DB (declaration-only extern)
 *   global_linkage      : "global_static" | "global_extern"
 *   access_kind         : "read" | "write" | "addr"
 *   access_line         : 1-indexed line number of the access site
 */
import cpp
import identity

string defFileOf(Variable g) { result = globalDefFile(g) }

string linkageOf(Variable g) {
  if isFileLocalGlobal(g)
  then result = "global_static"
  else result = "global_extern"
}

/**
 * The entity an access belongs to: the enclosing function when there is one,
 * else the file-scope VARIABLE whose initializer contains the access, else "".
 * Mirrors `edges/function_addresses.ql` — a static table that references
 * another global (`&other_tbl`, a nested pointer entry) is a real forward edge
 * from that table, not an anonymous file-scope event.
 */
string enclosingNameOf(Expr e) {
  exists(e.getEnclosingFunction()) and result = enclosingFunctionName(e)
  or
  not exists(e.getEnclosingFunction()) and
  exists(Variable v | v.getInitializer().getExpr().getAChild*() = e | result = globalName(v))
  or
  not exists(e.getEnclosingFunction()) and
  not exists(Variable v | v.getInitializer().getExpr().getAChild*() = e) and
  result = ""
}

string accessKindOf(VariableAccess va) {
  if exists(AddressOfExpr aoe | aoe.getOperand() = va)
  then result = "addr"
  else if va.isUsedAsLValue()
  then result = "write"
  else result = "read"
}

from VariableAccess va, Variable g
where g = va.getTarget() and isGlobalEntity(g)
select enclosingNameOf(va) as enclosing_name,
       pathOf(va.getFile()) as access_file,
       globalName(g) as global_name,
       defFileOf(g) as global_def_file,
       linkageOf(g) as global_linkage,
       accessKindOf(va) as access_kind,
       va.getLocation().getStartLine() as access_line
