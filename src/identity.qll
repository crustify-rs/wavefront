/**
 * Shared type-identity primitives for the wavefront query pack.
 *
 * C gives an aggregate a name in two places, and CodeQL surfaces only
 * one of them on the `UserType` itself:
 *
 *   struct tag { ... };                    -> getName() = "tag"
 *   typedef struct { ... } T;              -> getName() = "(unnamed class/struct/union)"
 *
 * The second spelling is not rare in OpenSSL -- `PACKET`, `OSSL_TIME`,
 * `CLIENTHELLO_MSG`, the `OSSL_HPKE_*` family -- and `(unnamed ...)` is a
 * plausible-looking non-empty string, so a query that keys on `getName()`
 * collapses every such type into one bucket instead of failing loudly.
 *
 * Two DIFFERENT resolutions apply, and they are not interchangeable:
 *
 *   shape A   typedef struct { int x; } T;          identity = the typedef name
 *             `t.x`                                 found SIDEWAYS, via the alias chain
 *
 *   shape B   struct N { struct { int x; } inner; }; identity = the enclosing named
 *             `n.inner.x`                            struct, found OUTWARD via the
 *                                                    qualifier chain (see
 *                                                    `edges/fa_with_root.ql`)
 *
 * This module owns shape A and the primitives both shapes need. Shape B
 * stays in `fa_with_root.ql`, which is where the qualifier expression is in
 * scope. A query that must handle both composes them -- see
 * `edges/field_accesses.ql`.
 *
 * Deliberately primitives, NOT policy: `edges/casts.ql` drops anonymous tags
 * outright and `edges/field_type_uses.ql` attributes shape B to the owning
 * root under a qualified member path. Those divergences are intentional, so
 * this module exposes the building blocks and lets each query choose.
 */

import cpp

/**
 * Repository-relative path, falling back to absolute for files outside the
 * source root (system/external headers) -- keeps system entities' identity
 * consistent with the T1 entity CSVs.
 */
string pathOf(File f) {
  if exists(f.getRelativePath())
  then result = f.getRelativePath()
  else result = f.getAbsolutePath()
}

/**
 * `cpp-all` spells an unnamed aggregate `(unnamed class/struct/union)`; a
 * flattened anonymous member can also surface as `""`. Both mean "this type
 * carries no C tag of its own".
 */
bindingset[n]
predicate isAnonNamed(string n) { n = "" or n.matches("(unnamed%") }

/** `t` has no C tag of its own. */
predicate isAnonymous(UserType t) { isAnonNamed(t.getName()) }

/**
 * A qualified name without its anonymous namespaces. The defining file tells
 * such entities apart, as it does a C `static`, and a name that starts with
 * `(` reads as an anonymous tag to every consumer, which would drop it.
 */
bindingset[name]
private string withoutAnonymousNamespaces(string name) {
  result = name.replaceAll("(unnamed namespace)::", "")
}

/** Keep the C tag for unqualified types and the full scope of C++ types. */
string declaredTypeName(UserType t) {
  if not isAnonymous(t) and exists(t.getQualifiedName())
  then result = withoutAnonymousNamespaces(t.getQualifiedName())
  else result = t.getName()
}

/** Struct and union precede Class, their common base in the CodeQL model. */
string typeKindOf(UserType t) {
  if t instanceof Struct then result = "struct"
  else if t instanceof Class then result = "class"
  else if t instanceof Enum then result = "enum"
  else if t instanceof TypedefType then result = "typedef"
  else result = "other"
}

private string memberQualifiers(Function fn) {
  exists(string constPart, string volatilePart, string refPart |
    (if fn instanceof ConstMemberFunction then constPart = " const" else constPart = "") and
    (if fn.(MemberFunction).getTypeOfThis().getBaseType().isVolatile()
     then volatilePart = " volatile" else volatilePart = "") and
    (if fn.(MemberFunction).isLValueRefQualified() then refPart = " &"
     else if fn.(MemberFunction).isRValueRefQualified() then refPart = " &&"
     else refPart = "") and
    result = constPart + volatilePart + refPart
  )
}

/**
 * Spelling of a type inside a function key. CodeQL's own `Type.toString()`
 * drops the scope of a named type, so `use(left::Tag)` and `use(right::Tag)`
 * would share the key `use(Tag)`, and spells every function pointer
 * `..(*)(..)`. A named type is spelled with its full scope; pointers,
 * references, cv-specifiers, arrays and function pointers are rebuilt
 * around the spelled base types. Any other type (a pointer to member, a
 * template parameter, `decltype`) keeps CodeQL's spelling. Total and
 * single-valued.
 */
string qualifiedTypeSpelling(Type t) {
  if
    t instanceof FunctionPointerIshType and
    t.(FunctionPointerIshType).getBaseType() instanceof RoutineType
  then result = routineSpelling(t.(FunctionPointerIshType).getBaseType(), routineMarkOf(t))
  else if t instanceof PointerType
  then result = qualifiedTypeSpelling(t.(PointerType).getBaseType()) + " *"
  else if t instanceof RValueReferenceType
  then result = qualifiedTypeSpelling(t.(RValueReferenceType).getBaseType()) + " &&"
  else if t instanceof LValueReferenceType
  then result = qualifiedTypeSpelling(t.(LValueReferenceType).getBaseType()) + " &"
  else if t instanceof SpecifiedType
  then
    result = placeSpecifiers(t.(SpecifiedType),
        qualifiedTypeSpelling(t.(SpecifiedType).getBaseType()))
  else if t instanceof ArrayType
  then result = qualifiedTypeSpelling(t.(ArrayType).getBaseType()) + arraySuffixOf(t.(ArrayType))
  else result = plainTypeSpelling(t)
}

/**
 * The spelling inside a routine's own signature. QL forbids recursion through
 * the `concat` that joins a routine's parameter types, so a function pointer
 * nested in another function pointer's signature keeps CodeQL's `..(*)(..)`.
 */
private string innerTypeSpelling(Type t) {
  if t instanceof PointerType
  then result = innerTypeSpelling(t.(PointerType).getBaseType()) + " *"
  else if t instanceof RValueReferenceType
  then result = innerTypeSpelling(t.(RValueReferenceType).getBaseType()) + " &&"
  else if t instanceof LValueReferenceType
  then result = innerTypeSpelling(t.(LValueReferenceType).getBaseType()) + " &"
  else if t instanceof SpecifiedType
  then
    result = placeSpecifiers(t.(SpecifiedType),
        innerTypeSpelling(t.(SpecifiedType).getBaseType()))
  else if t instanceof ArrayType
  then result = innerTypeSpelling(t.(ArrayType).getBaseType()) + arraySuffixOf(t.(ArrayType))
  else result = plainTypeSpelling(t)
}

/** A named type with its scope; anything else as CodeQL spells it. */
private string plainTypeSpelling(Type t) {
  if t instanceof UserType then result = canonicalTypeName(t.(UserType)) else result = t.toString()
}

/**
 * `const left::Tag *` is a pointer to const and `left::Tag * const` a const
 * pointer: the specifiers follow a pointer or array base and precede any
 * other base, as C++ writes them.
 */
bindingset[base]
private string placeSpecifiers(SpecifiedType t, string base) {
  exists(string specifiers |
    specifiers = concat(Specifier s | s = t.getASpecifier() | s.getName(), " " order by s.getName())
  |
    if
      t.getBaseType() instanceof PointerType or
      t.getBaseType() instanceof ArrayType or
      t.getBaseType() instanceof FunctionPointerIshType
    then result = base + " " + specifiers
    else result = specifiers + " " + base
  )
}

private string arraySuffixOf(ArrayType t) {
  if exists(t.getArraySize())
  then result = "[" + t.getArraySize().toString() + "]"
  else result = "[]"
}

/** `(*)` for a function pointer, `(&)` for a function reference, `(^)` for a block. */
private string routineMarkOf(FunctionPointerIshType t) {
  if t instanceof FunctionPointerType
  then result = "(*)"
  else if t instanceof FunctionReferenceType
  then result = "(&)"
  else result = "(^)"
}

/** `int (*)(left::Tag)`: the routine's return and parameter types, spelled. */
bindingset[mark]
private string routineSpelling(RoutineType rt, string mark) {
  exists(string returns, string parameters |
    (
      if exists(rt.getReturnType())
      then returns = innerTypeSpelling(rt.getReturnType())
      else returns = ".."
    ) and
    parameters = concat(int i | exists(rt.getParameterType(i)) |
      innerTypeSpelling(rt.getParameterType(i)), ", " order by i
    ) and
    result = returns + " " + mark + "(" + parameters + ")"
  )
}

/**
 * Top-level cv-qualifiers and typedefs never distinguish overloads:
 * `f(const int)` is `f(int)`, and `f(LeftAlias)` is `f(left::Tag)`. The
 * `min` keeps the key single-valued when a declaration and the definition
 * spell one parameter differently (`T arr[3]` against `T *arr`).
 */
private string parameterTypeSpelling(Parameter p) {
  result = min(string s | s = qualifiedTypeSpelling(p.getType().stripTopLevelSpecifiers()) | s)
}

/**
 * The scope part of a function key: the qualified name, or, for a member of
 * a class that has none (a lambda's closure type), the class's canonical
 * name and the member's. No result for a function with neither.
 */
private string scopedFunctionName(Function fn) {
  if exists(fn.getQualifiedName())
  then result = withoutAnonymousNamespaces(fn.getQualifiedName())
  else result = canonicalTypeName(fn.getDeclaringType()) + "::" + fn.getName()
}

/** The function key used by both entity and relationship queries. */
string functionNameOf(Function fn) {
  if fn.hasCLinkage() or not exists(scopedFunctionName(fn))
  then result = fn.getName()
  else
    exists(string parameters, string variadic |
      parameters = concat(int i | exists(fn.getParameter(i)) |
        parameterTypeSpelling(fn.getParameter(i)), ", " order by i
      ) and
      (if fn.isVarargs()
       then (if parameters = "" then variadic = "..." else variadic = ", ...")
       else variadic = "") and
      result = scopedFunctionName(fn) + "(" + parameters + variadic + ")" + memberQualifiers(fn)
    )
}

/**
 * Strip `DerivedType` wrappers (pointer / cv-qualified / array) off `t` and
 * bind every `UserType` reached on the way down, including `t` itself.
 */
predicate unwrappedUserType(Type t, UserType b) {
  b = t
  or
  unwrappedUserType(t.(DerivedType).getBaseType(), b)
}

/**
 * Shape A: the typedef name that IS `t`'s identity, for an anonymous
 * aggregate declared inline as a typedef's underlying type.
 *
 * Mirrors the rule `entities/types.ql`'s `unaliasedKindOf` uses to stamp
 * `struct_anonymous` / `union_anonymous` / `enum_anonymous`, so an access
 * site resolves to exactly the name `types_manifest.py` adopted as the
 * entry's identity -- by construction rather than by coincidence.
 *
 * `min(...)` keeps this single-valued when several typedefs alias one
 * anonymous aggregate; the composer picks one identity per type, so the
 * access side must not multiply rows. Has NO result when `t` is named or
 * when no typedef aliases it (shape B) -- callers must supply a fallback.
 */
string typedefIdentityOf(UserType t) {
  isAnonymous(t) and
  result = min(TypedefType td |
      unwrappedUserType(td.getBaseType(), t) and not isAnonNamed(td.getName())
    |
      declaredTypeName(td)
    )
}

/**
 * Total identity for a declaring aggregate: its own tag when it has one,
 * else its typedef name (shape A), else the unresolved placeholder.
 *
 * ALWAYS has a result, so a query selecting on it never silently drops a
 * row. A caller that can also resolve shape B should try that before
 * falling back here.
 */
string canonicalTypeName(UserType t) {
  if not isAnonymous(t)
  then result = declaredTypeName(t)
  else
    if exists(typedefIdentityOf(t))
    then result = typedefIdentityOf(t)
    else result = t.getName()
}

/**
 * `canonicalTypeName` widened to any `Type`, for call sites that hold the
 * result of a qualifier walk (`Type`, not `UserType`). Non-aggregate types
 * pass their own name through unchanged. Also total.
 */
string canonicalNameOfType(Type t) {
  if t instanceof UserType
  then result = canonicalTypeName(t.(UserType))
  else result = t.getName()
}

/*
 * ---------------------------------------------------------------------------
 * Aggregate OWNERSHIP identity: which named entity a field belongs to.
 *
 * `canonicalTypeName` above answers "what is this type called". These answer
 * "which entity declares this field, and where is it defined" — the pair every
 * field-keyed table joins on. They lived in `entities/fields.ql` while
 * `edges/field_type_uses.ql` hand-rolled its own struct-side resolution, and
 * the two drifted: `fields.ql` emitted every shape-A (`typedef struct {…} T;`)
 * field, `field_type_uses.ql` emitted NONE of them — 213 of 214 structs with
 * no field-type edge at all were shape A, against 0 of the 373 that had them.
 * The type DAG reads the T2 table, so every one of those field edges was
 * missing from the graph. One definition, imported by both.
 * ---------------------------------------------------------------------------
 */

/** The typedef that gives an otherwise-anonymous aggregate its name. */
predicate namingTypedef(UserType anon, TypedefType td) {
  isAnonymous(anon) and
  (anon instanceof Struct or anon instanceof Union) and
  unwrappedUserType(td.getBaseType(), anon)
}

/** Definition-site path of an aggregate, or "" when only declared. */
string anonDefFileOf(UserType anon) {
  if exists(anon.getDefinition())
  then result = pathOf(anon.getDefinition().getFile())
  else result = ""
}

/** Strip arrays and cv-qualifiers, but NOT pointers: a pointer to an
 * anonymous struct does not embed it. */
Type embeddedTypeOf(Type t) {
  if t instanceof ArrayType
  then result = embeddedTypeOf(t.(ArrayType).getBaseType())
  else
    if t instanceof SpecifiedType
    then result = embeddedTypeOf(t.(SpecifiedType).getBaseType())
    else result = t
}

/** The ANONYMOUS struct/union a field embeds by value, if any. */
UserType anonMemberAggregate(Field f) {
  result = embeddedTypeOf(f.getType()) and
  isAnonymous(result) and
  (result instanceof Struct or result instanceof Union)
}

/**
 * `f` is reachable from `root` through ANONYMOUS embedded members; `path` is
 * the dotted access path (`ext.hostname`). Recursion stops at the first NAMED
 * aggregate — a member of named type is its own entity with its own edge.
 */
predicate anonEmbeddedField(UserType root, Field f, string path) {
  exists(Field outer |
    outer.getDeclaringType() = root and
    f.getDeclaringType() = anonMemberAggregate(outer) and
    not isUnnamedMember(f) and
    path = memberPathPrefix(outer) + f.getName()
  )
  or
  exists(Field outer, string sub |
    outer.getDeclaringType() = root and
    anonEmbeddedField(anonMemberAggregate(outer), f, sub) and
    path = memberPathPrefix(outer) + sub
  )
}

/**
 * `f` has no declarator name: a C11 anonymous struct/union member
 * (`struct { union { int a; float b; }; }`). CodeQL names it
 * `(unknown field)`. Its own members are members of the enclosing aggregate
 * (`s.a`), so it names no field and contributes no access-path segment.
 */
predicate isUnnamedMember(Field f) { f.getName() = "(unknown field)" or f.getName() = "" }

/** The access-path segment `outer` contributes: `name.`, or nothing when unnamed. */
string memberPathPrefix(Field outer) {
  if isUnnamedMember(outer) then result = "" else result = outer.getName() + "."
}

/**
 * The manifest identity of an aggregate: its own tag when named, else the
 * typedef that names it. Single definition shared by every field-keyed query
 * so their struct sides cannot drift.
 */
predicate ownerOf(UserType t, string name, string file) {
  not isAnonymous(t) and
  name = declaredTypeName(t) and
  file = anonDefFileOf(t)
  or
  exists(TypedefType td |
    namingTypedef(t, td) and
    not isAnonNamed(td.getName()) and
    name = declaredTypeName(td) and
    file = anonDefFileOf(t)
  )
}

/** The anonymous aggregate a typedef names (`typedef struct {…} T;`). */
UserType anonBaseOf(TypedefType td) {
  unwrappedUserType(td.getBaseType(), result) and
  isAnonymous(result)
}

/**
 * The DEFINITION-site path of a type, the value every `*_def_file` column
 * carries. A typedef has no `getDefinition()` of its own, so shape A falls
 * through to the inline aggregate it names — that body site IS the type's
 * definition site.
 *
 * Shared because a `*_def_file` is half of every entity key: `entities/types.ql`
 * had this fallback and `edges/field_type_uses.ql`'s own `typeDefFileOf` did
 * not, so 1,133 field edges pointed at `(name, "")` while the node they meant
 * was keyed `(name, <path>)` — the target did not resolve and the edge died.
 */
string defFileOf(UserType t) {
  if exists(t.getDefinition())
  then result = pathOf(t.getDefinition().getFile())
  else
    if exists(anonBaseOf(t).getDefinition())
    then result = pathOf(anonBaseOf(t).getDefinition().getFile())
    else result = ""
}
