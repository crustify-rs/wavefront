/**
 * Enumerate every use of an enum's constant: an enumerator named
 * (`return REFTABLE_OUT_OF_MEMORY_ERROR;`, `case GIT_OBJECT_BLOB:`), on the
 * enum that declares it, from the function, global or macro that names it.
 *
 * Naming a constant needs its enum, whatever the type of the expression it
 * is written in: a function that returns `GIT_ENOTFOUND` through `int`, or
 * compares an `int` against `GIT_OBJECT_TREE`, names no enum type, so no
 * signature, local or cast records the enum (`signature_type_uses.ql`,
 * `local_type_uses.ql`). This table does.
 *
 * The user is:
 *
 *   - "function" : the function whose body the constant is in, an expansion
 *                  of a macro in it included, as other body edges count a
 *                  macro's expansion against the function that expands it;
 *   - "global"   : the global whose initializer it is in;
 *   - "macro"    : the macro whose replacement list writes the constant's
 *                  name, read off its expansions in the traced build as
 *                  `macro_references.ql` reads its other references
 *                  (`macro_bodies.qll`): a constant an argument passes is the
 *                  caller's, and one a nested macro writes that macro's.
 *
 * A constant written where neither applies, in another enum's initializer, a
 * type's array bound or bit-field width, or a file-scope `_Static_assert`,
 * has no row. Nor does one of an untagged enum no typedef names, which has
 * no identity of its own (`typeOwnerOf`), nor one in a macro the traced
 * build never expands.
 *
 * # cols:
 *   user_name      : the function, global or macro that names the constant
 *   user_def_file  : the user's definition file (a macro's `#define`), or ""
 *                    when the database holds no definition
 *   user_kind      : "function" | "global" | "macro"
 *   constant_name  : the enumerator's C identifier
 *   type_name      : the enum's identity, `typeOwnerOf`: its tag, or the
 *                    typedef naming an untagged enum
 *   type_def_file  : the enum's definition file
 *   use_file       : the file of the use; a macro's `#define`
 *   use_line       : 1-indexed line of the use; a macro's `#define`
 *
 * Results are distinct tuples: one constant named several times on one line
 * is one row.
 */
import cpp
import identity
import macro_bodies

string fnDefFile(Function fn) {
  if exists(fn.getDefinition())
  then result = pathOf(fn.getDefinition().getFile())
  else result = ""
}

string varDefFile(Variable v) {
  if exists(v.getDefinition())
  then result = pathOf(v.getDefinition().getFile())
  else result = ""
}

/** The function an expression sits in, or the global whose initializer holds
 * it, as `layout_uses.ql` attributes an expression. */
predicate exprUser(Expr e, string name, string file, string kind) {
  exists(Function fn | fn = e.getEnclosingFunction() |
    name = fn.getName() and file = fnDefFile(fn) and kind = "function"
  )
  or
  not exists(e.getEnclosingFunction()) and
  exists(GlobalVariable g | g = e.getEnclosingVariable() |
    name = g.getName() and file = varDefFile(g) and kind = "global"
  )
}

predicate use(EnumConstantAccess a, string uname, string ufile, string ukind, Location loc) {
  exprUser(a, uname, ufile, ukind) and loc = a.getLocation()
  or
  exists(Macro m, MacroInvocation mi |
    mi.getMacro() = m and
    fromReplacementList(mi, a) and
    a.getTarget().getName() = bodyIdentifier(m) and
    uname = m.getName() and
    ufile = pathOf(m.getFile()) and
    ukind = "macro" and
    loc = m.getLocation()
  )
}

from EnumConstantAccess a, EnumConstant c, string uname, string ufile, string ukind,
     string tname, string tfile, Location loc
where
  c = a.getTarget() and
  typeOwnerOf(c.getDeclaringEnum(), tname, tfile) and
  use(a, uname, ufile, ukind, loc)
select uname as user_name,
       ufile as user_def_file,
       ukind as user_kind,
       c.getName() as constant_name,
       tname as type_name,
       tfile as type_def_file,
       pathOf(loc.getFile()) as use_file,
       loc.getStartLine() as use_line
