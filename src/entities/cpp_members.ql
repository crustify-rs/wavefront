/**
 * Enumerate every C++ member function entity: what it is to its class.
 * Empty for C.
 *
 * A member implements its class, where a free function taking the class is
 * one of its consumers. The special members (constructors, the destructor,
 * copy and move) and a class-specific allocator are its lifecycle, which
 * the dependency graph folds into the class's node.
 *
 * # cols:
 *   function_name, function_def_file : the member's entity key, as in `functions.csv`
 *   class_name, class_def_file       : its class's entity key, as in `types.csv`
 *   member_kind     : `constructor` | `copy_constructor` | `move_constructor` |
 *                     `destructor` | `copy_assignment` | `move_assignment` |
 *                     `allocator` | `factory` | `conversion` | `operator` | `method`
 *   static, const, virtual, pure : as declared (`virtual` includes an
 *                     override of a virtual function)
 *   override        : it overrides a base class's virtual function
 *   access          : `public` | `protected` | `private`
 *   defaulted, deleted : `= default` or `= delete` in the source
 *   accessor        : `getter` | `setter` when its body only returns, or only
 *                     stores, one of its class's fields; "" otherwise
 *   accessor_field  : that field
 */

import cpp
import identity
import cppfacts

string b(boolean v) { result = flag(v) }

from MemberFunction m, Class c
where
  isEntityFunction(m) and
  c = m.getDeclaringType() and
  isEntityClass(c)
select functionName(m) as function_name, functionDefFile(m) as function_def_file,
  cppName(c) as class_name, defFileOf(c) as class_def_file, memberKindOf(m) as member_kind,
  b(any(boolean v | if m.isStatic() then v = true else v = false)) as static,
  b(any(boolean v | if m instanceof ConstMemberFunction then v = true else v = false)) as const,
  b(any(boolean v | if m.isVirtual() then v = true else v = false)) as virtual,
  b(any(boolean v | if m instanceof PureVirtualFunction then v = true else v = false)) as pure,
  b(any(boolean v | if exists(m.getAnOverriddenFunction()) then v = true else v = false)) as override,
  accessOf(m) as access,
  b(any(boolean v | if m.isDefaulted() then v = true else v = false)) as defaulted,
  b(any(boolean v | if m.isDeleted() then v = true else v = false)) as deleted,
  concat(string k | accessorOf(m, k, _) | k, "|") as accessor,
  concat(Field f | accessorOf(m, _, f) | f.getName(), "|") as accessor_field
