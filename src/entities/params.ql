/**
 * Every parameter of every function: one row per (function, position).
 *
 * `functions.csv` carries a function's parameter types only inside its
 * `signature` string, which prints typedef names as written -- `voidpf`
 * reads as a named type there although it is `void *`. This table states
 * each parameter's pointer shape resolved through typedefs, the way
 * `fields.csv` does for fields, so a consumer asking "is parameter N of f
 * type-erased?" reads a column instead of parsing C.
 *
 * # cols:
 *   function_name     : the function's C identifier
 *   function_def_file : repository-relative path of its definition, or ""
 *                       when only declared (same as `functions.csv`'s
 *                       `def_file`)
 *   position          : 0-based parameter index
 *   param_name        : the parameter's name as written, "" when unnamed
 *   param_type        : declared C type from `Type.toString()`
 *   ptr_depth         : pointer indirection count (`pointers.qll`)
 *   is_erased         : "true" iff the parameter is `void *` or `void **`
 *                       after typedefs and cv-qualifiers
 *
 * Consumer: `compose/t3.py` -- validates that a `chased_casts.csv` slot is
 * really type-erased.
 */
import cpp
import identity
import pointers

string functionDefFileOf(Function fn) {
  if exists(fn.getDefinition())
  then result = pathOf(fn.getDefinition().getFile())
  else result = ""
}

from Function fn, int pos, Parameter p
where p = fn.getParameter(pos)
select fn.getName() as function_name,
       functionDefFileOf(fn) as function_def_file,
       pos as position,
       p.getName() as param_name,
       p.getType().toString() as param_type,
       pointerDepthOf(p.getType()) as ptr_depth,
       isErasedOf(p.getType()) as is_erased
