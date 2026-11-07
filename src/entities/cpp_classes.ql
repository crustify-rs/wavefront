/**
 * Enumerate every C++ class, struct and union entity, with what its
 * declarations state of its lifecycle and its shape. Empty for C.
 *
 * # cols:
 *   name, def_file    : the class's entity key, as in `types.csv`
 *   keyword           : `class` | `struct` | `union`, as the class head writes it
 *   template_params   : a class template's parameters, `|`-separated; "" otherwise
 *   specializes, specializes_def_file
 *                     : an explicit or partial specialization's primary template
 *   abstract          : it declares or inherits a pure virtual function
 *   polymorphic       : it declares or inherits a virtual function
 *   final             : it is declared `final`
 *   default_ctor, copy_ctor, move_ctor, copy_assign, move_assign, dtor
 *                     : `user` | `defaulted` | `deleted` | `implicit` | "", how
 *                       it has each special member (see `cppfacts.qll`)
 *   copyable, movable : whether a copy or a move of it is well-formed: not
 *                       deleted or suppressed by its own declarations, nor by
 *                       a part it holds by value (field, base, container
 *                       element)
 *   trivial           : trivially copyable: nothing user-provided in its copy,
 *                       move or destruction, nothing virtual
 *   ctors             : its constructors other than the default, copy and move
 */

import cpp
import identity
import cppfacts

from Class c
where isEntityClass(c) and typeKindOf(c) != "other"
select cppName(c) as name, defFileOf(c) as def_file, keywordOf(c) as keyword,
  templateParamsOf(c) as template_params,
  concat(cppName(specializedTemplate(c))) as specializes,
  concat(defFileOf(specializedTemplate(c))) as specializes_def_file,
  flag(any(boolean b | if c instanceof AbstractClass then b = true else b = false)) as abstract,
  flag(any(boolean b | if c instanceof PolymorphicClass then b = true else b = false)) as polymorphic,
  flag(any(boolean b | if c.isFinal() then b = true else b = false)) as final,
  specialStatus(c, "default_ctor") as default_ctor, specialStatus(c, "copy_ctor") as copy_ctor,
  specialStatus(c, "move_ctor") as move_ctor, specialStatus(c, "copy_assign") as copy_assign,
  specialStatus(c, "move_assign") as move_assign, specialStatus(c, "dtor") as dtor,
  flag(any(boolean b | if nonCopyable(c) then b = false else b = true)) as copyable,
  flag(any(boolean b | if nonMovable(c) then b = false else b = true)) as movable,
  flag(any(boolean b | if isTrivial(c) then b = true else b = false)) as trivial,
  count(Constructor k |
    k.getDeclaringType() = c and
    userDeclared(k) and
    not k instanceof CopyConstructor and
    not k instanceof MoveConstructor and
    not k.isDefault()
  ) as ctors
