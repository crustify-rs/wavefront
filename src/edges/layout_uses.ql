/**
 * Enumerate every use of a struct's or union's LAYOUT: code that needs the
 * aggregate's members, size or alignment, and so cannot hold it through a
 * pointer it never looks behind.
 *
 * `use_kind` is one of:
 *
 *   - "field" : a member access, read, write or address-of (`p->x`, `&p->x`),
 *               on the aggregate that declares the member. An access through
 *               an anonymous member (`c->ext.port`) is a use of the named
 *               aggregate that holds it, through the access to the member;
 *   - "size"  : `sizeof` of the type or of an expression of it (`sizeof *p`),
 *               `_Alignof` of either, and `offsetof` on it (so `container_of`);
 *   - "value" : the aggregate held whole: a local, parameter, return or global
 *               of the type, and every expression of it used as a value rather
 *               than looked into: copied (`*a = *b`), passed or returned by
 *               value, or written as a compound literal or initializer list;
 *   - "index" : pointer arithmetic over it: `p + n`, `p - q`, `++p`, `p += n`,
 *               and indexing `p[i]`, all of which step by its size;
 *   - "embed" : a member of another aggregate that holds it by value, alone
 *               or as an array. The user is the embedding aggregate.
 *
 * An array of the aggregate counts as the aggregate in every kind. Uses that
 * hold the type only through a pointer -- a parameter of `T *`, a cast to
 * `T *`, a pointer comparison -- are no layout use and have no row. A macro's
 * uses are recorded where it is expanded, against the enclosing function.
 *
 * # cols:
 *   user_name      : the function, global, or (for "embed") aggregate that uses
 *                    the layout
 *   user_def_file  : the user's definition file, or "" when the database holds
 *                    no definition
 *   user_kind      : "function" | "global" | "type"
 *   type_name      : the aggregate's identity, `identity.qll`'s `ownerOf`: its
 *                    tag, or the typedef naming an untagged aggregate
 *   type_def_file  : the aggregate's definition file
 *   use_kind       : "field" | "size" | "value" | "index" | "embed"
 *   use_file       : the file of the use
 *   use_line       : 1-indexed line of the use
 *
 * Results are distinct tuples: several uses of one kind on one line are one
 * row. An aggregate with no identity of its own (an anonymous member, which
 * `ownerOf` does not name) has no rows; its uses reach the named aggregate
 * that holds it.
 */
import cpp
import identity

/** The aggregate a value of type `t` holds: `t` with typedefs, qualifiers and
 * array dimensions stripped, but never a pointer. */
Class valueAggregate(Type t) {
  exists(Type u | u = t.getUnspecifiedType() |
    (u instanceof Struct or u instanceof Union) and result = u
    or
    result = valueAggregate(u.(ArrayType).getBaseType())
  )
}

/** The aggregate a pointer (or array, which decays to one) of type `t` steps
 * over. */
Class steppedAggregate(Type t) {
  exists(Type u | u = t.getUnspecifiedType() |
    result = valueAggregate(u.(PointerType).getBaseType())
    or
    result = valueAggregate(u.(ArrayType).getBaseType())
  )
}

string fnDefFile(Function fn) {
  if exists(fn.getDefinition())
  then result = pathOf(fn.getDefinition().getFile())
  else result = ""
}

string varDefFile(Variable v) {
  if exists(v.getDefinition())
  then result = pathOf(v.getDefinition().getFile())
  else result = ""
}

/** The function an expression sits in, or the global whose initializer holds
 * it. */
predicate exprUser(Expr e, string name, string file, string kind) {
  exists(Function fn | fn = e.getEnclosingFunction() |
    name = fn.getName() and file = fnDefFile(fn) and kind = "function"
  )
  or
  not exists(e.getEnclosingFunction()) and
  exists(GlobalVariable g | g = e.getEnclosingVariable() |
    name = g.getName() and file = varDefFile(g) and kind = "global"
  )
}

/** `e` is not evaluated: it sits under `sizeof`, `_Alignof` or `offsetof`,
 * which read only types and member names. */
predicate unevaluated(Expr e) {
  e.getParent+() instanceof SizeofExprOperator
  or
  e.getParent+() instanceof AlignofExprOperator
  or
  e.getParent+() instanceof BuiltInOperationBuiltInOffsetOf
}

/** An expression of an aggregate type used whole, not looked into. */
predicate wholeValue(Expr e, Class agg) {
  agg = valueAggregate(e.getType()) and
  not e = any(FieldAccess fa).getQualifier() and
  not e = any(AddressOfExpr a).getOperand() and
  // `p[i].x` and `&p[i]` step over the aggregate: an index use. So does an
  // array that decays to a pointer to its first element.
  not e = any(ArrayExpr a).getArrayBase() and
  not e.getFullyConverted() instanceof ArrayToPointerConversion and
  not e.getConversion() instanceof ArrayToPointerConversion and
  not unevaluated(e) and
  // The parenthesis or conversion around an expression is the same use.
  not e instanceof ParenthesisExpr and
  not e instanceof Conversion and
  not e instanceof TypeName
}

/** The type an operand has where it is used: CodeQL hangs casts and implicit
 * conversions off an expression rather than making them its parent, so
 * `(char *)p - n` steps over `char`, not over `p`'s type. */
Type usedType(Expr e) { result = e.getFullyConverted().getType() }

/** A pointer step over the aggregate. */
predicate stepOver(Expr e, Class agg) {
  agg = steppedAggregate(usedType(e.(PointerArithmeticOperation).getAnOperand()))
  or
  agg = steppedAggregate(usedType(e.(CrementOperation).getOperand()))
  or
  agg = steppedAggregate(usedType(e.(AssignPointerAddExpr).getLValue()))
  or
  agg = steppedAggregate(usedType(e.(AssignPointerSubExpr).getLValue()))
  or
  agg = steppedAggregate(usedType(e.(ArrayExpr).getArrayBase()))
}

predicate sizeOf(Expr e, Class agg) {
  agg = valueAggregate(e.(SizeofTypeOperator).getTypeOperand())
  or
  agg = valueAggregate(usedType(e.(SizeofExprOperator).getExprOperand()))
  or
  agg = valueAggregate(e.(AlignofTypeOperator).getTypeOperand())
  or
  agg = valueAggregate(usedType(e.(AlignofExprOperator).getExprOperand()))
  or
  agg = valueAggregate(e.(BuiltInOperationBuiltInOffsetOf).getAChild().(TypeName).getType())
}

/** A layout use at an expression. */
predicate exprUse(Expr e, Class agg, string kind) {
  agg = e.(FieldAccess).getTarget().getDeclaringType() and kind = "field"
  or
  sizeOf(e, agg) and kind = "size"
  or
  wholeValue(e, agg) and kind = "value"
  or
  stepOver(e, agg) and kind = "index"
}

/** A declaration that holds the aggregate by value. */
predicate declUse(Element d, Class agg, string uname, string ufile, string ukind) {
  exists(LocalScopeVariable v | d = v and agg = valueAggregate(v.getType()) |
    exists(Function fn |
      fn = v.(LocalVariable).getFunction() or fn = v.(Parameter).getFunction()
    |
      uname = fn.getName() and ufile = fnDefFile(fn) and ukind = "function"
    )
  )
  or
  exists(GlobalVariable g | d = g and agg = valueAggregate(g.getType()) |
    uname = g.getName() and ufile = varDefFile(g) and ukind = "global"
  )
  or
  exists(Function fn | d = fn and agg = valueAggregate(fn.getType()) |
    uname = fn.getName() and ufile = fnDefFile(fn) and ukind = "function"
  )
}

from Class agg, string uname, string ufile, string ukind, string tname, string tfile,
     string kind, Location loc
where
  ownerOf(agg, tname, tfile) and
  (
    exists(Expr e |
      exprUse(e, agg, kind) and exprUser(e, uname, ufile, ukind) and loc = e.getLocation()
    )
    or
    exists(Element d |
      declUse(d, agg, uname, ufile, ukind) and kind = "value" and loc = d.getLocation()
    )
    or
    // "embed": the named aggregate that holds a member of the type by value,
    // directly or through anonymous members.
    exists(Field f, UserType owner |
      agg = valueAggregate(fieldType(f)) and
      kind = "embed" and
      ukind = "type" and
      loc = f.getLocation() and
      ownerOf(owner, uname, ufile) and
      (
        f.getDeclaringType() = owner
        or
        anonEmbeddedField(owner, f, _)
      )
    )
  )
select uname as user_name,
       ufile as user_def_file,
       ukind as user_kind,
       tname as type_name,
       tfile as type_def_file,
       kind as use_kind,
       pathOf(loc.getFile()) as use_file,
       loc.getStartLine() as use_line
