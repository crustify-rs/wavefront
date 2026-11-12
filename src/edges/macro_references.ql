/**
 * What each macro's replacement list references: the functions, globals and
 * macros it names, and the types it names, with the fields it accesses in them.
 *
 * A `#define` is text, so what a name in it denotes is read off its
 * expansions in the traced build: an element an expansion of the macro
 * produces (`MacroInvocation.getAnExpandedElement()`) that names an entity
 * the replacement list itself writes. An expansion also holds what its
 * arguments and the macros nested in it produce. An element an argument
 * produces keeps the argument's own location, inside the invocation, while
 * one the replacement lists produce, the macro's or a nested macro's, takes
 * the invocation's; and the name must be an identifier of the replacement
 * list, outside string and character literals, and not one of the macro's
 * parameters:
 *
 *   #define DROP(p)       do { mem_free(p); (p) = NULL; } while (0)
 *   #define APPLY(fn, x)  fn(x)
 *   #define RENEW(x)      do { DROP(x); NEW(x); } while (0)
 *
 * `DROP` references `mem_free` and `NULL`; `APPLY(mem_free, q)` calls
 * `mem_free` through its argument, which is the caller's reference, not
 * `APPLY`'s; `RENEW` references `DROP` and `NEW`, and not what they call.
 *
 * A macro the traced build never expands has no rows: its names are not
 * resolved (G3), nor is a name the body only pastes together (`a##b`).
 * A field access is the macro's when the replacement list names both the
 * field and its type (`((struct pool *)(p))->used`): one into whatever its
 * argument points at (`(p)->used`) is generic over that type, which is the
 * caller's.
 *
 * # cols:
 *   macro_name     : the macro's C identifier
 *   macro_def_file : repository-relative path of its `#define`
 *   ref_kind       : `function` (called or address taken), `global`,
 *                    `macro` (expanded by the replacement list), or `type`
 *                    (a cast, `sizeof`, `_Alignof` or local declaration
 *                    naming it, or a field access into it that names it)
 *   ref_name       : the referenced entity's C identifier; a type's tag,
 *                    or for an untagged aggregate the typedef naming it
 *   ref_def_file   : the file defining it, "" when only declared
 *   field_name     : for a field access, the field the replacement list
 *                    names; "" otherwise
 */
import cpp
import identity
import macro_bodies

string functionDefFileOf(Function f) {
  if exists(f.getDefinition())
  then result = pathOf(f.getDefinition().getFile())
  else result = ""
}

string globalDefFileOf(GlobalVariable g) {
  if exists(g.getDefinition())
  then result = pathOf(g.getDefinition().getFile())
  else result = ""
}

string typeDefFileOf(UserType t) {
  if exists(t.getDefinition())
  then result = pathOf(t.getDefinition().getFile())
  else result = ""
}

/** A type an expanded element names: by a cast, `sizeof`, `_Alignof` or a local declaration. */
Type namedType(Locatable e) {
  result = e.(Cast).getType() and not e.(Cast).isImplicit()
  or
  result = e.(SizeofTypeOperator).getTypeOperand()
  or
  result = e.(AlignofTypeOperator).getTypeOperand()
  or
  result = e.(DeclStmt).getADeclaration().(LocalVariable).getType()
}

predicate reference(Macro m, string kind, string name, string defFile, string field) {
  exists(MacroInvocation mi, Locatable e |
    mi.getMacro() = m and
    fromReplacementList(mi, e)
  |
    exists(Function f |
      f = e.(FunctionCall).getTarget() or f = e.(FunctionAccess).getTarget()
    |
      kind = "function" and
      name = f.getName() and
      defFile = functionDefFileOf(f) and
      field = ""
    )
    or
    exists(GlobalVariable g | g = e.(VariableAccess).getTarget() |
      kind = "global" and
      name = g.getName() and
      defFile = globalDefFileOf(g) and
      field = ""
    )
    or
    exists(UserType t |
      unwrappedUserType(namedType(e), t) and
      not isAnonymous(t) and
      (t instanceof Struct or t instanceof Enum or t instanceof TypedefType)
    |
      kind = "type" and
      name = t.getName() and
      defFile = typeDefFileOf(t) and
      field = ""
    )
    or
    exists(Field f, UserType owner |
      f = e.(FieldAccess).getTarget() and
      owner = f.getDeclaringType()
    |
      kind = "type" and
      name = canonicalTypeName(owner) and
      not isAnonNamed(name) and
      defFile = typeDefFileOf(owner) and
      field = f.getName() and
      field = bodyIdentifier(m)
    )
  ) and
  name = bodyIdentifier(m)
  or
  exists(MacroInvocation mi, MacroInvocation nested |
    mi.getMacro() = m and
    nested.getParentInvocation() = mi
  |
    kind = "macro" and
    name = nested.getMacroName() and
    name = bodyIdentifier(m) and
    defFile = pathOf(nested.getMacro().getFile()) and
    field = ""
  )
}

from Macro m, string kind, string name, string defFile, string field
where reference(m, kind, name, defFile, field)
select m.getName() as macro_name, pathOf(m.getFile()) as macro_def_file,
  kind as ref_kind, name as ref_name, defFile as ref_def_file, field as field_name
