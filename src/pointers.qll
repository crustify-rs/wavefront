/**
 * Pointer shape of a declared type, shared by `entities/fields.ql` and
 * `entities/params.ql` so a field and a parameter of one type agree.
 */

import cpp

/** Holds if `t`'s unwrap chain reaches a `RoutineType` (a function type). */
predicate reachesRoutineType(Type t) {
  t instanceof RoutineType
  or
  reachesRoutineType(t.(DerivedType).getBaseType())
  or
  reachesRoutineType(t.(TypedefType).getBaseType())
}

/** A typedef whose unwrap chain reaches a `RoutineType` — terminal for the
 * pointer walk: the identity is the typedef name, not the anonymous routine. */
predicate isCallbackTypedef(Type t) {
  t instanceof TypedefType and reachesRoutineType(t)
}

/** Holds if a pointer level is reachable from `t` through qualifiers/typedefs. */
predicate reachesPointer(Type t) {
  t instanceof PointerType
  or
  t instanceof FunctionPointerIshType
  or
  reachesPointer(t.(SpecifiedType).getBaseType())
  or
  reachesPointer(t.(TypedefType).getBaseType())
}

/**
 * Pointer indirection count for a FIELD's declared type — the authoritative
 * "is this field a pointer?" signal, replacing the consumer's old heuristic of
 * looking for a literal `*` in `field_type`.
 *
 * That heuristic was blind to the two shapes where C hides the star behind a
 * name, both of which then collapsed to a bare scalar field with NO pointer
 * record and hence no ownership analysis:
 *
 *   - an OBJECT-pointer typedef (`typedef struct _filesec *filesec_t;`) —
 *     `Type.toString()` prints `filesec_t`, and types.csv cannot help because
 *     `aliasOf` unwraps the star, making `typedef T *P` indistinguishable from
 *     `typedef T P`;
 *   - a bare function pointer (`int (*ctrl)(BIO *, int, long, void *)`) —
 *     modelled as `FunctionPointerIshType`, which is NOT a `PointerType`.
 *
 * Mirrors `edges/function_pointer_args.ql::pointerDepth` so a field and a
 * parameter of the same type report the same depth.
 */
int pointerDepthOf(Type t) {
  if isCallbackTypedef(t)
  then result = 1
  else
    if t instanceof FunctionPointerIshType
    then result = 1
    else
      if t instanceof PointerType
      then result = 1 + pointerDepthOf(t.(PointerType).getBaseType())
      else
        if t instanceof SpecifiedType and reachesPointer(t.(SpecifiedType).getBaseType())
        then result = pointerDepthOf(t.(SpecifiedType).getBaseType())
        else
          if t instanceof TypedefType and reachesPointer(t.(TypedefType).getBaseType())
          then result = pointerDepthOf(t.(TypedefType).getBaseType())
          else result = 0
}


/**
 * `t` is TYPE-ERASED: `void *` or `void **`, seen through typedefs and
 * cv-qualifiers at every level (`const void *`, `void *const *`, zlib's
 * `typedef void *voidpf`). The slot names no type, so what it holds is a
 * cast away.
 */
predicate isErasedPointer(Type t) {
  exists(PointerType p | p = t.getUnspecifiedType() |
    p.getBaseType().getUnspecifiedType() instanceof VoidType
    or
    p.getBaseType().getUnspecifiedType().(PointerType).getBaseType().getUnspecifiedType()
      instanceof VoidType
  )
}

/** `isErasedPointer` as a column value. */
string isErasedOf(Type t) { if isErasedPointer(t) then result = "true" else result = "false" }
