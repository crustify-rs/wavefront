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
      td.getName()
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
  then result = cppName(t)
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
  // `Class` covers C's structs and unions, and C++'s classes.
  if exists(anon.(Class).getDefinition())
  then result = pathOf(anon.(Class).getDefinition().getFile())
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

/**
 * The type `f` is declared with. The extractor can give one field several
 * types, one per translation-unit variant of a type it names: a struct that
 * some TUs complete and others leave incomplete is two entities, so a pointer
 * to it is two pointer types, and a callback typedef whose signature names it
 * gives the field one routine type per variant, none of them the typedef. The
 * declaration entries keep the type as written, so a field with several types
 * takes theirs; every other field keeps its one.
 */
Type fieldType(Field f) {
  if strictcount(f.getType()) > 1 and exists(f.getADeclarationEntry().getType())
  then result = f.getADeclarationEntry().getType()
  else result = f.getType()
}

/** The ANONYMOUS struct/union a field embeds by value, if any. */
UserType anonMemberAggregate(Field f) {
  result = embeddedTypeOf(fieldType(f)) and
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
  not isInstantiatedType(t) and
  not isSyntheticType(t) and
  name = cppName(t) and
  file = anonDefFileOf(t)
  or
  exists(TypedefType td |
    namingTypedef(t, td) and
    not isAnonNamed(td.getName()) and
    name = td.getName() and
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
  exists(UserType c | c = canonicalUserType(t) |
    if exists(c.getDefinition())
    then result = pathOf(c.getDefinition().getFile())
    else
      if exists(anonBaseOf(c).getDefinition())
      then result = pathOf(anonBaseOf(c).getDefinition().getFile())
      else result = ""
  )
}

/*
 * ---------------------------------------------------------------------------
 * C++ identity.
 *
 * C names an entity by its identifier alone. C++ scopes it in namespaces and
 * classes, overloads it, and instantiates it from templates, so the
 * identifier names many entities and the database holds one entity per
 * instantiation. Every query names a C++ entity through the predicates below,
 * so that each table keys it the same way:
 *
 *   - a scoped entity is named by its qualified name, `geo::Circle::area`;
 *     an anonymous namespace adds nothing, since the defining file already
 *     tells its entities apart, as it does a C `static`, and an inline
 *     namespace adds nothing either (`std::__cxx11::basic_string` is
 *     `std::basic_string`);
 *   - an instantiation is named, and keyed, as the template it was
 *     instantiated from: `Pool<Circle>` is `geo::Pool`, and its members are
 *     `geo::Pool`'s. A primary class template is named without its parameter
 *     list, an explicit or partial specialization with its arguments
 *     (`geo::Pool<bool>`);
 *   - a lambda is part of the function that writes it: what its body calls
 *     and touches, that function calls and touches;
 *   - an overloaded function takes its parameter types as a suffix,
 *     `geo::total_area(const Scene &)`, so overloads stay distinct entities.
 *     Where two overloads' suffixes read alike, their types differing only
 *     in a namespace or an enclosing class, both take the scoped spelling,
 *     `use(left::Tag)` and `use(right::Tag)`;
 *   - a member the compiler generates is no entity: it is in no source file.
 *     Whether a class has it is a fact about the class (`cpp_classes.csv`).
 *
 * A C entity is never scoped, instantiated or overloaded, so every predicate
 * below yields its plain identifier and C tables are unchanged.
 * ---------------------------------------------------------------------------
 */

/**
 * `f` is C++: a translation unit compiled as C++, or a header one includes.
 * A C codebase has none, so nothing below changes its names.
 */
cached
predicate isCppFile(File f) {
  f.compiledAsCpp()
  or
  exists(File tu | tu.compiledAsCpp() and tu.getAnIncludedFile+() = f)
}

/** The prefix a namespace contributes to the names it scopes: `geo::`. */
string namespacePrefix(Namespace ns) {
  ns instanceof GlobalNamespace and result = ""
  or
  not ns instanceof GlobalNamespace and
  if ns.isAnonymous() or ns.isInline()
  then result = namespacePrefix(ns.getParentNamespace())
  else result = namespacePrefix(ns.getParentNamespace()) + ns.getName() + "::"
}

/**
 * The class template, or the member of one, that `t` was instantiated from;
 * `t` itself when it is no instantiation.
 */
UserType canonicalUserType(UserType t) {
  if t.(Class).isConstructedFrom(_)
  then exists(UserType u | t.(Class).isConstructedFrom(u) | result = canonicalUserType(u))
  else result = t
}

/** `t` is an instantiation, or a class nested in one: its template is the entity. */
predicate isInstantiatedType(UserType t) {
  t.(Class).isConstructedFrom(_)
  or
  t instanceof AliasTemplateInstantiationType
  or
  isInstantiatedType(t.getDeclaringType())
}

/**
 * A class written by the compiler or standing in for a template parameter:
 * a lambda's closure type, a template parameter, a proxy class. None names
 * an entity of the codebase.
 */
predicate isSyntheticType(UserType t) {
  t instanceof Closure or
  t instanceof TypeTemplateParameter or
  t instanceof ProxyClass or
  t instanceof TemplateTemplateParameterInstantiation
}

/** The scope prefix of a declaration: its enclosing classes and namespaces. */
string scopePrefix(Declaration d) {
  if d.isMember() and isCppFile(d.getFile())
  then result = cppName(canonicalUserType(d.getDeclaringType())) + "::"
  else
    if exists(d.getNamespace())
    then result = namespacePrefix(d.getNamespace())
    else result = ""
}

/**
 * A user type's name: its identifier in C; in C++ its qualified name,
 * without the parameter list of a primary template, and the template's for
 * an instantiation. Every query names a type by this, or by
 * `canonicalTypeName`, which falls back to a naming typedef.
 */
string cppName(UserType t) {
  exists(UserType c | c = canonicalUserType(t) |
    if isAnonNamed(c.getName())
    then result = c.getName()
    else
    if c instanceof TemplateClass
    then result = scopePrefix(c) + c.getSimpleName()
    else result = scopePrefix(c) + c.getName()
  )
}

/** The canonical function of `f`: the template it was instantiated from, or, for a lambda's call operator, the function that writes the lambda. */
Function canonicalFunction(Function f) {
  if f.isConstructedFrom(_)
  then exists(Function g | f.isConstructedFrom(g) | result = canonicalFunction(g))
  else
    if f = any(Closure c).getLambdaFunction()
    then
      exists(Closure c | f = c.getLambdaFunction() |
        result = canonicalFunction(c.getLambdaExpression().getEnclosingFunction())
      )
    else result = f
}

/** `f` is an entity of its own: no instantiation, no lambda, no compiler-generated member. */
predicate isEntityFunction(Function f) {
  canonicalFunction(f) = f and
  not f.isCompilerGenerated() and
  not isInstantiatedType(f.getDeclaringType()) and
  not isSyntheticType(f.getDeclaringType())
}

/** A function's qualified name, before any overload suffix. */
string baseFunctionName(Function f) { result = scopePrefix(f) + f.getName() }

/** The parameter types of `f`, and `const` on a const member, as an overload suffix. */
string overloadSuffix(Function f) {
  result =
    "(" +
      concat(int i |
        exists(f.getParameter(i))
      |
        typeSpelling(f.getParameter(i).getType()), ", " order by i
      ) + ")" + any(string c | if f instanceof ConstMemberFunction then c = " const" else c = "")
}

/**
 * A parameter type as an overload suffix spells it: as written, less the
 * policies a standard container takes by default
 * (`vector<Shape *, allocator<Shape *>>` is `vector<Shape *>`).
 */
string typeSpelling(Type t) {
  result =
    t.toString()
        .regexpReplaceAll("basic_string<char, char_traits<char>, allocator<char>>", "string")
        .regexpReplaceAll(", (allocator|default_delete|char_traits|less|hash|equal_to)<([^<>]|<([^<>]|<[^<>]*>)*>)*>", "")
}

/**
 * The user type a parameter type names, through pointers, references,
 * qualifiers and arrays, when its scope can be written into the spelling:
 * a plain identifier, so no instantiation, and no closure or template
 * parameter.
 */
private predicate scopedLeaf(Type t, UserType u) {
  unwrappedUserType(t, u) and
  u.getName().regexpMatch("[A-Za-z_][A-Za-z0-9_]*") and
  not isSyntheticType(u)
}

/** `typeSpelling` with the scope of the type `t` names: `const Reader::Options &`. */
private string scopedLeafSpelling(Type t) {
  if exists(UserType u | scopedLeaf(t, u))
  then
    exists(UserType u | scopedLeaf(t, u) |
      result = typeSpelling(t).regexpReplaceAll("\\b" + u.getName() + "\\b", cppName(u))
    )
  else result = typeSpelling(t)
}

/**
 * A parameter type spelled with what `typeSpelling` leaves out: the scope of
 * the type it names, `const Reader::Options &` for `const Options &`, and a
 * function pointer's signature, `int (*)(left::Tag)` for `..(*)(..)`. A
 * function pointer inside that signature keeps `typeSpelling`'s form.
 */
string scopedTypeSpelling(Type t) {
  if t.stripTopLevelSpecifiers().(FunctionPointerIshType).getBaseType() instanceof RoutineType
  then
    exists(FunctionPointerIshType p, RoutineType r, string mark |
      p = t.stripTopLevelSpecifiers() and
      r = p.getBaseType() and
      (
        if p instanceof FunctionPointerType
        then mark = "*"
        else
          if p instanceof FunctionReferenceType
          then mark = "&"
          else mark = "^"
      )
    |
      result =
        scopedLeafSpelling(r.getReturnType()) + " (" + mark + ")(" +
          concat(int i |
            exists(r.getParameterType(i))
          |
            scopedLeafSpelling(r.getParameterType(i)), ", " order by i
          ) + ")"
    )
  else result = scopedLeafSpelling(t)
}

/** `overloadSuffix` with `scopedTypeSpelling` for each parameter type. */
string scopedOverloadSuffix(Function f) {
  result =
    "(" +
      concat(int i |
        exists(f.getParameter(i))
      |
        scopedTypeSpelling(f.getParameter(i).getType()), ", " order by i
      ) + ")" + any(string c | if f instanceof ConstMemberFunction then c = " const" else c = "")
}

/** `f` shares its qualified name with another C++ entity function of another signature. */
predicate isOverloaded(Function f) {
  isCppFile(f.getFile()) and
  exists(Function g |
    g != f and
    isEntityFunction(g) and
    baseFunctionName(g) = baseFunctionName(f) and
    (
      overloadSuffix(g) != overloadSuffix(f) or
      scopedOverloadSuffix(g) != scopedOverloadSuffix(f)
    )
  )
}

/**
 * `f` has an overload whose suffix reads the same as its own, their
 * parameter types differing only in what `typeSpelling` leaves out:
 * `use(left::Tag)` and `use(right::Tag)` are both `use(Tag)`.
 */
predicate hasLookalikeOverload(Function f) {
  exists(Function g |
    g != f and
    isEntityFunction(g) and
    baseFunctionName(g) = baseFunctionName(f) and
    overloadSuffix(g) = overloadSuffix(f) and
    scopedOverloadSuffix(g) != scopedOverloadSuffix(f)
  )
}

/**
 * The name a function's entity is keyed by, `canonicalFunction` applied. An
 * overload takes its suffix as `overloadSuffix` spells it, and the scoped
 * spelling only where that one would name two overloads alike.
 */
string functionName(Function f) {
  exists(Function c | c = canonicalFunction(f) |
    if isOverloaded(c)
    then
      if hasLookalikeOverload(c)
      then result = baseFunctionName(c) + scopedOverloadSuffix(c)
      else result = baseFunctionName(c) + overloadSuffix(c)
    else result = baseFunctionName(c)
  )
}

/**
 * The file that defines a function's entity: the canonical function's
 * definition, or, for a template member whose body the database records
 * only in its instantiations, an instantiation's.
 */
string functionDefFile(Function f) {
  exists(Function c | c = canonicalFunction(f) |
    if exists(c.getDefinition())
    then result = pathOf(c.getDefinition().getFile())
    else
      if exists(Function i | canonicalFunction(i) = c and exists(i.getDefinition()))
      then
        result =
          min(Function i | canonicalFunction(i) = c and exists(i.getDefinition()) |
            pathOf(i.getDefinition().getFile())
          )
      else result = ""
  )
}

/**
 * A variable of static storage the codebase names at file or class scope:
 * a C global, a C++ namespace variable, or a static data member. A variable
 * template's instantiations are its template's.
 */
predicate isGlobalEntity(Variable v) {
  (v instanceof GlobalOrNamespaceVariable or v.(MemberVariable).isStatic()) and
  not v.isConstructedFrom(_) and
  not isInstantiatedType(v.getDeclaringType())
}

/** A global's name: its identifier in C, its qualified name in C++. */
string globalName(Variable v) { result = scopePrefix(v) + v.getName() }

/** The kind a type entity is recorded as. A C++ class is a struct: Rust has no other. */
string typeKindOf(UserType t) {
  if t instanceof Struct
  then result = "struct"
  else
    if t instanceof Union
    then result = "union"
    else
      if t instanceof Enum
      then result = "enum"
      else
        if t instanceof TypedefType
        then result = "typedef"
        else
          if t instanceof Class and not isSyntheticType(t)
          then result = "struct"
          else result = "other"
}

/**
 * Template arguments that a standard container takes by default and that
 * name no dependency: its allocator, deleter, traits and comparator.
 */
predicate isDefaultTemplatePolicy(Type t) {
  exists(string n | n = t.(Class).getSimpleName() |
    n = ["allocator", "default_delete", "char_traits", "less", "hash", "equal_to", "greater"]
  ) and
  t.(Class).getNamespace().getParentNamespace*().getName() = "std"
}

/**
 * The user types a type names: itself, through pointers, references, arrays
 * and qualifiers, a routine type's parameters and return, and an
 * instantiation's type arguments (`std::vector<std::unique_ptr<Shape>>`
 * names `std::vector`, `std::unique_ptr` and `Shape`), less the policies a
 * container takes by default.
 */
predicate reachableUserType(Type outer, UserType t) {
  outer = t and not isDefaultTemplatePolicy(t)
  or
  reachableUserType(outer.(DerivedType).getBaseType(), t)
  or
  reachableUserType(outer.(RoutineType).getReturnType(), t)
  or
  reachableUserType(outer.(RoutineType).getAParameterType(), t)
  or
  // A C++ alias names what it aliases: `using Shapes = std::vector<Shape *>`
  // names `Shape`. Only C++ files: a C typedef stays an alias the composer
  // resolves.
  reachableUserType(outer.(TypedefType).getBaseType(), t) and
  isCppFile(outer.getFile())
  or
  exists(Type arg |
    arg = outer.(Class).getATemplateArgument() and
    outer.(Class).isConstructedFrom(_) and
    not isDefaultTemplatePolicy(arg) and
    reachableUserType(arg, t)
  )
}

/**
 * The entity whose body `f`'s body is part of: `f` itself, or, for a
 * lambda's call operator, the function that writes the lambda. None for an
 * instantiation, or a member the compiler generates: what an instantiation's
 * body reaches depends on its template arguments, which the template's users
 * name, so the template depends only on what its own body names without
 * them.
 */
Function bodyOwner(Function f) {
  if f = any(Closure c).getLambdaFunction()
  then
    exists(Closure c | f = c.getLambdaFunction() |
      result = bodyOwner(c.getLambdaExpression().getEnclosingFunction())
    )
  else (
    not f.isConstructedFrom(_) and
    not isInstantiatedType(f.getDeclaringType()) and
    not f.isCompilerGenerated() and
    result = f
  )
}

/** The outermost class enclosing `t`, its template's for an instantiation. */
UserType outermostClass(UserType t) {
  exists(UserType c | c = canonicalUserType(t) |
    if exists(c.getDeclaringType())
    then result = outermostClass(c.getDeclaringType())
    else result = c
  )
}

/**
 * A call from an instantiation's body that its template's body makes too:
 * from one member of a class template to another, which the template makes
 * whatever its arguments (`SkipList<K, C>::Insert` calls `NewNode`). The
 * database leaves such a call unresolved in the template, where it depends
 * on the template's parameters, and resolves it in each instantiation.
 * Calls into the arguments' members (`compare_(a, b)`) stay with the
 * template's users, as `bodyOwner` says.
 */
predicate templateSelfCall(Function enc, Function callee) {
  enc.isConstructedFrom(_) and
  not enc = any(Closure c).getLambdaFunction() and
  outermostClass(canonicalFunction(enc).getDeclaringType()) instanceof TemplateClass and
  outermostClass(canonicalFunction(callee).getDeclaringType()) =
    outermostClass(canonicalFunction(enc).getDeclaringType())
}

/** The entity name of the function whose body holds `e`. */
string enclosingFunctionName(Element e) {
  result = functionName(bodyOwner(e.(Expr).getEnclosingFunction()))
  or
  result = functionName(bodyOwner(e.(MacroInvocation).getEnclosingFunction()))
}

/** A global's file-local linkage: C's `static`, which a static data member is not. */
predicate isFileLocalGlobal(Variable g) { g.isStatic() and not g.isMember() }

/** The file that defines a global, or "" when only declared. */
string globalDefFile(Variable g) {
  if exists(g.getDefinition())
  then result = pathOf(g.getDefinition().getFile())
  else result = ""
}
