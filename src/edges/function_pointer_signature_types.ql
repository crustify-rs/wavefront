/**
 * Enumerate every user-defined type an inline function pointer's signature
 * names: the types `edges/function_pointer_uses.ql`'s function pointers depend
 * on. The walk is `signature_type_uses.ql`'s: pointers, arrays and qualifiers
 * unwrap, a nested function pointer's signature is walked into, and a typedef
 * stops the walk, the composer resolving it.
 *
 * Keyed by signature alone: one signature names the same types wherever it is
 * written, so each row holds for every file the function pointer is homed in.
 *
 * # cols:
 *   signature     : the function pointer, as `function_pointer_uses.ql` writes it
 *   type_name     : the user-defined type's C tag or typedef name
 *   type_kind     : "struct" | "union" | "enum" | "typedef"
 *   type_def_file : the type's definition file, or "" when only declared
 *   position      : "return" | "param_<i>", the first it is found at
 */
import cpp

string pathOf(File f) {
  if exists(f.getRelativePath())
  then result = f.getRelativePath()
  else result = f.getAbsolutePath()
}

/** `Union` is a subclass of `Struct` in `cpp-all`: tested first. */
string kindOf(UserType t) {
  if t instanceof Union then result = "union"
  else if t instanceof Struct then result = "struct"
  else if t instanceof Enum then result = "enum"
  else if t instanceof TypedefType then result = "typedef"
  else result = "other"
}

string typeDefFileOf(UserType t) {
  if exists(t.getDefinition())
  then result = pathOf(t.getDefinition().getFile())
  else result = ""
}

string paramsOf(FunctionPointerType t) {
  t.getNumberOfParameters() = 0 and result = "void"
  or
  t.getNumberOfParameters() > 0 and
  result =
    concat(int i | i in [0 .. t.getNumberOfParameters() - 1] |
        t.getParameterType(i).toString(), ", " order by i)
}

string signatureOf(FunctionPointerType t) {
  result = t.getReturnType().toString() + " (*)(" + paramsOf(t) + ")"
}

predicate reachableUserType(Type outer, UserType t) {
  outer = t
  or
  reachableUserType(outer.(DerivedType).getBaseType(), t)
  or
  reachableUserType(outer.(RoutineType).getReturnType(), t)
  or
  reachableUserType(outer.(RoutineType).getAParameterType(), t)
}

/** `t` is found at `pos` of `fp`'s signature; `ord` orders the positions. */
predicate found(FunctionPointerType fp, UserType t, string pos, int ord) {
  reachableUserType(fp.getReturnType(), t) and pos = "return" and ord = -1
  or
  exists(int i |
    reachableUserType(fp.getParameterType(i), t) and
    pos = "param_" + i.toString() and ord = i
  )
}

from FunctionPointerType fp, UserType t, string pos
where
  found(fp, t, pos, min(int r | found(fp, t, _, r))) and
  t.getName() != "" and
  not t.getName().matches("(unnamed%") and
  kindOf(t) != "other"
select signatureOf(fp) as signature,
       t.getName() as type_name,
       kindOf(t) as type_kind,
       typeDefFileOf(t) as type_def_file,
       pos as position
