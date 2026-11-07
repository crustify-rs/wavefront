/**
 * Enumerate every C++ override: a member function and the base class's
 * virtual function it overrides directly. Empty for C.
 *
 * An override implements its base's interface, a trait method in Rust, so
 * it depends on the function it overrides.
 *
 * # cols:
 *   function_name, function_def_file     : the overriding member's entity key
 *   overridden_name, overridden_def_file : the overridden one's
 */

import cpp
import identity

from MemberFunction m, MemberFunction o
where
  isEntityFunction(m) and
  exists(m.getFile().getRelativePath()) and
  o = canonicalFunction(m.getAnOverriddenFunction())
select functionName(m) as function_name, functionDefFile(m) as function_def_file,
  functionName(o) as overridden_name, functionDefFile(o) as overridden_def_file
