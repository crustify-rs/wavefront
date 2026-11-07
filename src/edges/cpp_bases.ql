/**
 * Enumerate every C++ base-class derivation between entities. Empty for C.
 *
 * A derived class embeds its bases, so it depends on each as on a field's
 * type: the base is written first. A base that is an instantiation
 * (`Base<Derived>`, `std::enable_shared_from_this<T>`) is its template.
 *
 * # cols:
 *   derived_name, derived_def_file : the derived class's entity key
 *   base_name, base_def_file       : the base's
 *   position  : the base's place in the class head, from 0
 *   virtual   : a virtual base
 *   access    : `public` | `protected` | `private`
 */

import cpp
import identity
import cppfacts

string accessOfDerivation(ClassDerivation d) {
  if d.hasSpecifier("public")
  then result = "public"
  else
    if d.hasSpecifier("protected")
    then result = "protected"
    else result = "private"
}

from Class c, ClassDerivation d, Class base, int i
where
  isEntityClass(c) and
  d = c.getDerivation(i) and
  base = d.getBaseClass() and
  not isSyntheticType(base)
select cppName(c) as derived_name, defFileOf(c) as derived_def_file, cppName(base) as base_name,
  defFileOf(base) as base_def_file, i as position,
  flag(any(boolean v | if d.isVirtual() then v = true else v = false)) as virtual,
  accessOfDerivation(d) as access
