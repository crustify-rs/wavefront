/**
 * Enumerate every use of a function-pointer type written INLINE, without a
 * typedef: `int (*open)(struct ctx *, const char *)` as a field, a parameter,
 * a return, a local, a global, or a cast target. A function pointer a typedef
 * declares (`typedef int (*visit_cb)(...)`) is that typedef's, and its uses
 * are the typedef's (`signature_type_uses.ql`, `callback_call_sites.ql`); it
 * has no row here.
 *
 * An inline function pointer has no declaration of its own, so its identity
 * is its signature and the file it is homed in: its user's definition file,
 * or, for a user defined nowhere, the file it is written in. One signature
 * written in two files is two entities, as two anonymous structs are.
 *
 * A pointer to, or an array of, function pointers uses the function pointer.
 *
 * # cols:
 *   user_name      : the function, global, or (for "field") aggregate using it
 *   user_def_file  : the user's definition file, or "" when the database holds
 *                    no definition
 *   user_kind      : "function" | "global" | "type"
 *   signature      : the function pointer's type, return and parameter types
 *                    as written: `int (*)(struct ctx *, const char *)`. A
 *                    nested function pointer is `..(*)(..)`, and a variadic
 *                    one's `...` is not written: `cpp-all` records none
 *   def_file       : the file the function pointer is homed in, as above
 *   use_kind       : "field" | "param" | "return" | "local" | "global" | "cast"
 *   use_file       : the file of the use
 *   use_line       : 1-indexed line of the use
 */
import cpp
import identity

/** The inline function pointer a declared type holds: `t` stripped of
 * qualifiers, arrays and pointers, never of a typedef. */
FunctionPointerType inlineFp(Type t) {
  result = t
  or
  result = inlineFp(t.(SpecifiedType).getBaseType())
  or
  result = inlineFp(t.(ArrayType).getBaseType())
  or
  result = inlineFp(t.(PointerType).getBaseType())
}

/** The parameter list of a function pointer, as C writes it. */
string paramsOf(FunctionPointerType t) {
  t.getNumberOfParameters() = 0 and result = "void"
  or
  t.getNumberOfParameters() > 0 and
  result =
    concat(int i | i in [0 .. t.getNumberOfParameters() - 1] |
        t.getParameterType(i).toString(), ", " order by i)
}

/** The function pointer's signature: `int (*)(struct ctx *, void *)`. */
string signatureOf(FunctionPointerType t) {
  result = t.getReturnType().toString() + " (*)(" + paramsOf(t) + ")"
}

string fnFile(Function fn) {
  if exists(fn.getDefinition())
  then result = pathOf(fn.getDefinition().getFile())
  else result = ""
}

string varFile(Variable v) {
  if exists(v.getDefinition())
  then result = pathOf(v.getDefinition().getFile())
  else result = ""
}

predicate use(string uname, string ufile, string ukind, FunctionPointerType t,
              string useKind, Location loc) {
  exists(Field f, UserType owner |
    t = inlineFp(fieldType(f)) and
    useKind = "field" and
    ukind = "type" and
    loc = f.getLocation() and
    ownerOf(owner, uname, ufile) and
    (f.getDeclaringType() = owner or anonEmbeddedField(owner, f, _))
  )
  or
  exists(Function fn |
    uname = fn.getName() and ufile = fnFile(fn) and ukind = "function"
  |
    t = inlineFp(fn.getType()) and useKind = "return" and loc = fn.getLocation()
    or
    exists(Parameter p |
      p = fn.getAParameter() and t = inlineFp(p.getType()) and
      useKind = "param" and loc = p.getLocation()
    )
    or
    exists(LocalVariable v |
      v.getFunction() = fn and t = inlineFp(v.getType()) and
      useKind = "local" and loc = v.getLocation()
    )
    or
    exists(Cast c |
      not c.isImplicit() and c.getEnclosingFunction() = fn and
      t = inlineFp(c.getType()) and useKind = "cast" and loc = c.getLocation()
    )
  )
  or
  exists(GlobalVariable g |
    t = inlineFp(g.getType()) and useKind = "global" and ukind = "global" and
    uname = g.getName() and ufile = varFile(g) and loc = g.getLocation()
  )
}

from string uname, string ufile, string ukind, FunctionPointerType t,
     string useKind, Location loc, string home
where
  use(uname, ufile, ukind, t, useKind, loc) and
  (if ufile != "" then home = ufile else home = pathOf(loc.getFile()))
select uname as user_name,
       ufile as user_def_file,
       ukind as user_kind,
       signatureOf(t) as signature,
       home as def_file,
       useKind as use_kind,
       pathOf(loc.getFile()) as use_file,
       loc.getStartLine() as use_line
