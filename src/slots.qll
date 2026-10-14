/**
 * Slot-mediated casts: the named types that cross a value SLOT -- a
 * function parameter, a function's return, or a struct field -- and the
 * slots a value is handed between unchanged.
 *
 * `edges/casts.ql` sees a cast only when BOTH its operand and its result
 * strip to a named struct. The type-erasure idiom never satisfies that:
 *
 *     av_log(avctx, ...);                   AVCodecContext* -> void*   (call site)
 *     void av_log(void *avcl, ...)
 *         { av_vlog(avcl, ...); }           void* -> void*             (forward)
 *     void av_vlog(void *avcl, ...)
 *         { ... *(AVClass **) avcl ... }    void* -> AVClass**         (read)
 *
 * Each half has `void` on one side, so the raw cast graph has no row for
 * any of them. Read per slot, they are three edges:
 *
 *     type AVCodecContext -> param av_log.0        (from)
 *     param av_log.0      -> param av_vlog.0       (forward)
 *     param av_vlog.0     -> type AVClass          (to)
 *
 * and the composer joins them into `AVCodecContext casted_to AVClass`.
 *
 * STRICTLY SYNTACTIC. Every edge is a conversion or a hand-off written AT
 * the slot access itself (through parentheses and conversions only); no
 * dataflow library is imported. A value that passes through a local first
 * (`void *p = s->opaque; T *t = p;`) is not followed -- an edge is missed,
 * never invented. Field slots are field-based (one summary per field, all
 * instances merged), the standard type-based approximation.
 *
 * Endpoint encoding, shared by `edges/arg_casts.ql` and
 * `edges/field_casts.ql`:
 *
 *   kind     name          file                   member
 *   type     struct tag    tag's definition file  ""
 *   param    function      function's def file    parameter position
 *   ret      function      function's def file    "ret"
 *   field    owner tag     owner's def file       field name
 *
 * plus, per endpoint, `decl` -- the named struct the slot is DECLARED to
 * hold ("" when the slot is type-erased: `void *`, `uint8_t *`, `intptr_t`)
 * -- and `ctype`, the declared C type as written. A `from` or `to` row is
 * emitted only when the crossing type differs from the slot's `decl`; the
 * composer seeds each slot with its own `decl`.
 */

import cpp
import identity

/**
 * The first named `Struct` (unions included -- `Union` extends `Struct`)
 * reached by peeling pointers, arrays, cv-qualifiers and typedefs off `t`.
 * Same rule as `edges/casts.ql`, so the two cast graphs share identities.
 */
Struct namedStruct(Type t) {
  result = t and not isAnonNamed(canonicalTypeName(result))
  or
  result = namedStruct(t.(DerivedType).getBaseType())
  or
  result = namedStruct(t.(TypedefType).getBaseType())
}

/** The named struct `t` strips to, or "" when it strips to none. */
string declOf(Type t) {
  if exists(namedStruct(t))
  then result = canonicalTypeName(namedStruct(t))
  else result = ""
}

string fnFileOf(Function f) {
  if exists(f.getDefinition())
  then result = pathOf(f.getDefinition().getFile())
  else result = ""
}

string structFileOf(Struct s) { result = defFileOf(s) }

/**
 * Only POINTER slots carry a cast: an `int` field returned or an enum passed
 * on hands a value along, not a type. Typedefs and cv-qualifiers are seen
 * through (`AVBufferRef *`, `const void *`, `uint8_t *` all qualify).
 */
predicate pointerSlot(Type t) { t.getUnspecifiedType() instanceof PointerType }

/**
 * A parameter whose every access reads the value the caller passed: never
 * assigned, incremented or address-taken in its function. Accesses of any
 * other parameter may see a value the function produced itself, so they
 * carry no slot edge.
 */
predicate stableParam(Parameter p) {
  exists(p.getFunction().getBlock()) and
  not exists(Assignment a | a.getLValue().(VariableAccess).getTarget() = p) and
  not exists(CrementOperation c | c.getOperand().(VariableAccess).getTarget() = p) and
  not exists(AddressOfExpr a | a.getOperand().(VariableAccess).getTarget() = p)
}

/*
 * ---------------------------------------------------------------------------
 * Slot SOURCES: expressions that read a slot's value.
 * ---------------------------------------------------------------------------
 */

/** `e` reads parameter `pos` of `f`. */
predicate readsParam(Expr e, Function f, int pos) {
  exists(Parameter p |
    e.(VariableAccess).getTarget() = p and
    p = f.getParameter(pos) and
    stableParam(p) and
    e.getEnclosingFunction() = f
  )
}

/** `e` reads the return value of a direct call to `f`. */
predicate readsRet(Expr e, Function f) { e.(FunctionCall).getTarget() = f }

/** `e` reads field `fld` (an rvalue access, not the target of a store). */
predicate readsField(Expr e, Field fld) {
  e.(FieldAccess).getTarget() = fld and
  not exists(Assignment a | a.getLValue() = e) and
  not exists(CrementOperation c | c.getOperand() = e) and
  not exists(AddressOfExpr a | a.getOperand() = e)
}

/*
 * ---------------------------------------------------------------------------
 * Slot SINKS: expressions whose value is stored INTO a slot. `v` is the
 * unconverted value; its conversions up to the slot are implicit.
 * ---------------------------------------------------------------------------
 */

/** `v` is passed as argument `pos` of a direct call to `f`. */
predicate storesParam(Expr v, Function f, int pos) {
  exists(FunctionCall c |
    c.getTarget() = f and
    exists(f.getParameter(pos)) and
    v = c.getArgument(pos).getUnconverted()
  )
}

/** `v` is returned from `f`. */
predicate storesRet(Expr v, Function f) {
  exists(ReturnStmt r |
    r.getEnclosingFunction() = f and
    v = r.getExpr().getUnconverted()
  )
}

/** `v` is stored into field `fld`, by assignment or aggregate initializer. */
predicate storesField(Expr v, Field fld) {
  exists(AssignExpr a |
    a.getLValue().(FieldAccess).getTarget() = fld and
    v = a.getRValue().getUnconverted()
  )
  or
  exists(ClassAggregateLiteral lit | v = lit.getAFieldExpr(fld).getUnconverted())
}

/*
 * ---------------------------------------------------------------------------
 * Slot endpoints. `kind` is "param" | "ret" | "field" (see the module doc).
 * ---------------------------------------------------------------------------
 */

predicate paramSlot(Function f, int pos, string name, string file, string member,
                    string decl, string ctype) {
  exists(Parameter p | p = f.getParameter(pos) and pointerSlot(p.getType()) |
    name = f.getName() and file = fnFileOf(f) and member = pos.toString() and
    decl = declOf(p.getType()) and ctype = p.getType().toString()
  )
}

predicate retSlot(Function f, string name, string file, string member,
                  string decl, string ctype) {
  pointerSlot(f.getType()) and
  name = f.getName() and file = fnFileOf(f) and member = "ret" and
  decl = declOf(f.getType()) and ctype = f.getType().toString()
}

predicate fieldSlot(Field fld, string name, string file, string member,
                    string decl, string ctype) {
  pointerSlot(fld.getType()) and
  ownerOf(fld.getDeclaringType(), name, file) and
  member = fld.getName() and
  decl = declOf(fld.getType()) and ctype = fld.getType().toString()
}

/** `e` reads the slot named by the remaining columns. */
predicate slotRead(Expr e, string kind, string name, string file, string member,
                   string decl, string ctype) {
  exists(Function f, int pos |
    readsParam(e, f, pos) and kind = "param" and
    paramSlot(f, pos, name, file, member, decl, ctype)
  )
  or
  exists(Function f |
    readsRet(e, f) and kind = "ret" and retSlot(f, name, file, member, decl, ctype)
  )
  or
  exists(Field fld |
    readsField(e, fld) and kind = "field" and
    fieldSlot(fld, name, file, member, decl, ctype)
  )
}

/** `v` is stored into the slot named by the remaining columns. */
predicate slotStore(Expr v, string kind, string name, string file, string member,
                    string decl, string ctype) {
  exists(Function f, int pos |
    storesParam(v, f, pos) and kind = "param" and
    paramSlot(f, pos, name, file, member, decl, ctype)
  )
  or
  exists(Function f |
    storesRet(v, f) and kind = "ret" and retSlot(f, name, file, member, decl, ctype)
  )
  or
  exists(Field fld |
    storesField(v, fld) and kind = "field" and
    fieldSlot(fld, name, file, member, decl, ctype)
  )
}

/**
 * `T` is a named struct some conversion on `e` (up to its fully converted
 * form, implicit conversions included) produces.
 */
Struct convertedTo(Expr e) {
  exists(Conversion c | c = e.getConversion+() | result = namedStruct(c.getType()))
}

/** A named struct as an endpoint: `decl` is the tag itself, `ctype` "". */
predicate typeEnd(Struct s, string name, string file, string member, string decl,
                  string ctype) {
  name = canonicalTypeName(s) and not isAnonNamed(name) and file = structFileOf(s) and
  member = "" and decl = name and ctype = ""
}

/** Where the edge is written: enclosing function, or "" at file scope. */
predicate siteOf(Expr e, string fn, string file, int line) {
  (if exists(e.getEnclosingFunction())
   then fn = e.getEnclosingFunction().getName() and file = fnFileOf(e.getEnclosingFunction())
   else (fn = "" and file = pathOf(e.getFile()))) and
  line = e.getLocation().getStartLine()
}

/**
 * One slot edge, `src -> dst`:
 *
 *   from     type -> slot   a value of named type D is stored into a slot
 *                           whose declared struct is not D, and the value
 *                           is not itself a slot read (that one arrives as
 *                           a `forward` from a slot whose `decl` is D)
 *   to       slot -> type   a slot read is converted to named type T, other
 *                           than the slot's declared struct
 *   forward  slot -> slot   a slot read is stored, unchanged, into a slot
 *
 * `param -> ret` forwards are left out: an identity-style function would
 * join every caller's argument to every caller's result, an unrealizable
 * path the field-insensitive composer could not tell apart.
 */
predicate slotEdge(string rel,
                   string sk, string sn, string sf, string sm, string sd, string sc,
                   string dk, string dn, string df, string dm, string dd, string dc,
                   Expr at) {
  rel = "from" and
  exists(Struct d |
    d = namedStruct(at.getType()) and
    sk = "type" and typeEnd(d, sn, sf, sm, sd, sc) and
    slotStore(at, dk, dn, df, dm, dd, dc) and
    sd != dd and
    not slotRead(at, _, _, _, _, _, _)
  )
  or
  rel = "to" and
  exists(Struct t |
    slotRead(at, sk, sn, sf, sm, sd, sc) and
    t = convertedTo(at) and
    dk = "type" and typeEnd(t, dn, df, dm, dd, dc) and
    dd != sd
  )
  or
  rel = "forward" and
  slotRead(at, sk, sn, sf, sm, sd, sc) and
  slotStore(at, dk, dn, df, dm, dd, dc) and
  not (sk = "param" and dk = "ret")
}
