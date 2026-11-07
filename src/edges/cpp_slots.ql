/**
 * Enumerate what the C++ type of every parameter, return, field and global
 * says of the value it holds: whether it owns it, shares it or borrows it,
 * whether it may be null, how many it holds, and whether it is text. Empty
 * for C, whose types say none of it.
 *
 * Each slot's type is read as a chain of layers down to the element it
 * holds (`cppfacts.qll`): `const std::vector<std::unique_ptr<Shape>> &` is
 * `cref;vector;unique_ptr;class` over `geo::Shape`. The composer derives a
 * slot's pointer properties from the chain (`docs/cpp.md`). A slot whose
 * type is a plain scalar or enum says nothing and has no row.
 *
 * # cols:
 *   owner_kind     : `param` | `return` | `field` | `global`
 *   owner_name, owner_def_file : the function, type or global's entity key
 *   member         : the parameter's position, `ret`, the field's name, or ""
 *   member_name    : the parameter's name; "" otherwise
 *   chain          : the type's layers, outermost first
 *   element_name, element_def_file : the user type the chain ends in, if any
 *   type           : the declared type, as written
 */

import cpp
import identity
import cppfacts

predicate slot(
  string kind, string owner, string ownerFile, string member, string memberName, Type t,
  Declaration decl
) {
  exists(Function f, int i, Parameter p |
    isEntityFunction(f) and p = f.getParameter(i) and t = p.getType() and decl = f
  |
    kind = "param" and owner = functionName(f) and ownerFile = functionDefFile(f) and
    member = i.toString() and memberName = p.getName()
  )
  or
  exists(Function f |
    isEntityFunction(f) and t = f.getType() and decl = f and
    not f instanceof Constructor and not f instanceof Destructor
  |
    kind = "return" and owner = functionName(f) and ownerFile = functionDefFile(f) and
    member = "ret" and memberName = ""
  )
  or
  exists(Field fld |
    ownerOf(fld.getDeclaringType(), owner, ownerFile) and
    not isUnnamedMember(fld) and
    t = fieldType(fld) and
    decl = fld
  |
    kind = "field" and member = fld.getName() and memberName = ""
  )
  or
  exists(Variable g | isGlobalEntity(g) and t = g.getType() and decl = g |
    kind = "global" and owner = globalName(g) and ownerFile = globalDefFile(g) and
    member = "" and memberName = ""
  )
}

from
  string kind, string owner, string ownerFile, string member, string memberName, Type t,
  Declaration decl, string chain, Type elem
where
  slot(kind, owner, ownerFile, member, memberName, t, decl) and
  // The codebase's own declarations, in C++: the standard library's are no
  // slot of the codebase, and a C type says none of this.
  exists(decl.getFile().getRelativePath()) and
  isCppFile(decl.getFile()) and
  chainOf(t, chain, elem) and
  informativeChain(chain)
select kind as owner_kind, owner as owner_name, ownerFile as owner_def_file, member,
  memberName as member_name, chain, elemName(elem) as element_name,
  elemDefFile(elem) as element_def_file, typeSpelling(t) as type
