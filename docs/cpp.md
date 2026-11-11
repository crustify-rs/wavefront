# C++

Wavefront orders a C++ codebase with the same pipeline, tables and graph as a
C one. The difference is what the source states. A C codebase leaves a type's
lifecycle, its methods, its subtypes and the ownership of its pointers to
convention, so wavefront infers what it can, and users record the rest as
findings or T3 rows. A C++ codebase declares all four in its types, and
wavefront reads them from the declarations. It follows no value and runs no
data-flow analysis: every fact below comes from a declaration, a class head,
a signature or a one-statement body.

The `cpp_*` tables hold these facts ([Tables](#tables)). They are empty for
a C codebase, so a C codebase's tables, graph, records and schedules are the
same as before C++ support.

## Identity

C++ scopes, overloads and instantiates its entities, so one identifier names
many of them, and the database holds one entity per instantiation. Every
query names a C++ entity the same way (`src/identity.qll`), so the tables
still join on name and file:

| C++ | named | example |
|---|---|---|
| a namespace or class member | by its qualified name | `geo::Circle::area` |
| an anonymous or inline namespace | without it: the file tells anonymous entities apart, as it does a C `static` | `std::basic_string`, not `std::__cxx11::basic_string` |
| a class template | without its parameter list | `geo::Pool` |
| an explicit or partial specialization | with its arguments | `geo::Pool<bool>` |
| an instantiation, and its members | as its template, and the template's members | `Pool<Circle>::put` is `geo::Pool::put` |
| an overloaded function | with its parameter types | `geo::total_area(const Scene &)` |
| overloads whose parameter types read alike | with those types' scope, and a function pointer's signature | `use(left::Tag)` and `use(right::Tag)`, not `use(Tag)` twice |
| a lambda | as part of the function that writes it | |
| a member the compiler generates | as no entity: it is in no source | |

A C++ class is a type of kind `struct`, as in Rust; `cpp.keyword` keeps the
class head's `class`, `struct` or `union`. A header is C++ when a translation
unit compiled as C++ includes it.

## What the type system states

| C convention | C++ declaration | where wavefront records it | effect on the graph |
|---|---|---|---|
| `widget_new`, `widget_free`, `widget_dup` | constructors, destructor, copy and move | `cpp_members.member_kind`, `cpp_classes` special members | folded into the class's node, as its `cpp.lifecycle` |
| `widget_get_x(w)` | a member function | `cpp_members` | a symbol that `implements` its class and depends on it |
| a field accessor | a member whose one statement returns or stores a field | `cpp_members.accessor` | `member.accessor` |
| a base as first member, casts | a base class | `cpp_bases` | `derived -> base`, in every graph |
| a vtable struct | virtual functions and overrides | `cpp_members`, `cpp_overrides` | `override -> overridden` |
| a `void *` container, a type-minting macro | a class template | identity, `cpp_classes.template_params` | a user depends on the template and its type arguments |
| `char *` text, `T *` + length | `std::string`, `std::vector<T>`, `std::span<T>` | `cpp_slots` | pointer properties of the slot |
| owned or borrowed `T *` | `std::unique_ptr<T>`, `const T &`, `std::shared_ptr<T>` | `cpp_slots` | pointer properties of the slot |
| copyable or not, by convention | deleted or suppressed copy and move | `cpp_classes.copyable`, `movable`, `trivial` | `cpp` |

### Lifecycle

A class's constructors, destructor, copy and move constructors, copy and move
assignments, and its class-specific `operator new` and `operator delete` are
its lifecycle. The graph folds them into the class's node: the node depends
on what they depend on, every edge to one of them is an edge to the class,
and the class's `cpp.lifecycle` lists them with the role each plays, in the
vocabulary of [`type-lifecycle.md`](type-lifecycle.md):

| member | role |
|---|---|
| constructor | `constructor_init`: it initializes storage its caller provides |
| destructor | `disposer`: it releases what the object owns, and leaves its storage to whoever allocated it |
| copy constructor | `cloner_deep` |
| copy assignment | `cloner_deep_assign` |
| move constructor, move assignment | `move`, `move_assign`: Rust moves by value |
| `operator new`, `operator delete` | `allocator` |

A deleted member is folded with no role: it states that the class has none.

A C type's lifecycle routines are not folded ([`graph.md`](graph.md#nodes)):
which routines play which role is a user's judgement there, and the graph
must not depend on one. A C++ class's lifecycle is the language's, not a
judgement, so folding it keeps the graph a function of the source. What
folding costs is the same as in C: a constructor's body joins the class's
dependencies, so a class whose constructor calls one of its own methods
forms a cycle with it, which is cut as any cycle is.

A static member that returns a new object of its class, by value, raw
pointer or owning wrapper, is a `factory`. It is a constructor by
convention, not by the language, so it stays a member node.

`cpp.special_members` gives how the class has each special member: `user`,
`defaulted` or `deleted` in the source, `implicit` when the database
records the compiler's, or `""` when it records none. The database records
an implicit member only where the compiler declared it, so `""` is not
"absent". `copyable` and `movable` give the language's answer: a copy is
ill-formed when the class deletes or suppresses it (a user-declared move
suppresses the implicit copy; a private copy constructor is the pre-C++11
idiom), or when a part it holds by value is not copyable: a field, a base,
or the element of a standard container. `trivial` marks a trivially
copyable class, a Rust `Copy`.

### Implementers and consumers

A member function implements its class. It depends on the class, which it
takes as its receiver, and carries `member`: the class it `implements`, its
`member_kind`, whether it is static, const, virtual or pure, its access,
and the functions it `overrides`. A free function that takes the class is
one of its consumers and carries no `member`. A class's record lists its
`implementers`.

A member whose body is one statement that returns a field of its object,
its address, or a view of it (`.get()`, `.c_str()`, `.data()`) is a
`getter`; one whose body is one statement that stores a parameter into a
field is a `setter`. `member.accessor` names the field.

### Polymorphism

A class depends on each of its bases, as on a field's type: it embeds them.
The class head states the direction, so a base pair is never ordered by
cast centrality, and a downcast written in a body adds no edge the other way.
A base pair needs no T3 `base_derived` row.

An override depends on the virtual function it overrides, its trait method
in Rust, so a base's interface is written before its implementations. A call
through a virtual function is a call of the function its static type names,
the base's, which is the dependency a translation has.

### Generics

A class template is one node, and its instantiations are uses of it: a use of
`Pool<Circle>` depends on `geo::Pool` and on `geo::Circle`. A specialization
depends on its primary template. The standard library's containers are
external nodes, and their default allocators, deleters, traits and
comparators name no dependency.

A template's body depends on what it names without its parameters. A call
that depends on them is resolved only in each instantiation, where it
reaches the arguments' members (`compare_(a, b)` calls the comparator its
user chose), so it is a dependency of the template's users, which name the
arguments. Calls from one member of a class template to another
(`SkipList::Insert` calls `NewNode`) are the template's own whatever its
arguments, and are taken from its instantiations.

### Ownership, nullability and cardinality

A slot's type, a parameter's, a return's, a field's or a global's, is read as
a chain of layers down to the element it holds (`src/cppfacts.qll`):
`const std::vector<std::unique_ptr<Shape>> &` is `cref;vector;unique_ptr;class`
over `geo::Shape`. The pointer properties
([`pointer-properties.md`](pointer-properties.md)) the chain states are
composed into the record as `cpp`, beside the field or under the function's
`cpp.params` and `cpp.return`:

| outermost layer | `owned` | `borrowed` | `nullable` | `mutable` |
|---|---|---|---|---|
| a value, a container, a `std::string` | true | false | false | |
| `unique_ptr` | true | false | true | true |
| `shared_ptr` | true, `shared` | false | true | true |
| `weak_ptr` | false | true | true | |
| `optional` | true | false | true | |
| `T &` / `const T &` | false | true | false | true / false |
| `T &&` | true: moved in | false | false | true |
| `string_view`, `span` | false | true | false | false |
| `T *` / `const T *` | open | open | open | true / false |

`cardinality` is what the first layer below the indirection holds:
`string` for `std::string`, `std::string_view` and `char *`, `array` for a
sequence container, `std::span`, a C array or `unique_ptr<T[]>`, `map` for an
associative container, and `scalar` otherwise. A property the type leaves
open is absent, so the slots that still need a finding are the raw pointers.

## What stays open

Without data-flow, the declarations leave these open:

- **raw pointers**: a `T *` states its shape and mutability, but not who owns
  it, whether it may be null, or how many it points at. These slots remain
  findings, as in C;
- **type erasure**: a `void *` slot is recovered from its casts and corrected
  in T3, as in C;
- **implicit special members**: the database records the compiler's
  declarations only where it made them, and `copyable` and `movable` follow
  the language's rules for deleted and suppressed members, not overload
  resolution, so a copy that SFINAE or a constraint removes reads as
  copyable;
- **dependent template code**: what a template's body reaches through its
  parameters is its users' dependency, through the arguments they name;
- **indirect calls**: a `std::function`, a function pointer or a virtual call
  is a dependency on its type or its static target, not on what it calls at
  run time;
- **the borrow a getter returns**: a getter that returns a reference borrows
  from its object, which the record does not state as a lifetime;
- **what the build does not compile**, as in C.

## Tables

Each table is keyed by the entities' names and files as the T1 tables name
them. All are empty for C.

### `t1/cpp_classes.csv`

| column | meaning |
|---|---|
| `name`, `def_file` | the class's key, as in `types.csv` |
| `keyword` | `class`, `struct` or `union` |
| `template_params` | a class template's parameters, `|`-separated |
| `specializes`, `specializes_def_file` | a specialization's primary template |
| `abstract`, `polymorphic`, `final` | it has a pure virtual function, a virtual function, the `final` specifier |
| `default_ctor`, `copy_ctor`, `move_ctor`, `copy_assign`, `move_assign`, `dtor` | `user`, `defaulted`, `deleted`, `implicit` or `""` |
| `copyable`, `movable`, `trivial` | its value semantics |
| `ctors` | its constructors other than the default, copy and move |

### `t1/cpp_members.csv`

| column | meaning |
|---|---|
| `function_name`, `function_def_file` | the member's key, as in `functions.csv` |
| `class_name`, `class_def_file` | its class's key |
| `member_kind` | `constructor`, `copy_constructor`, `move_constructor`, `destructor`, `copy_assignment`, `move_assignment`, `allocator`, `factory`, `conversion`, `operator` or `method` |
| `static`, `const`, `virtual`, `pure`, `override` | as declared |
| `access` | `public`, `protected` or `private` |
| `defaulted`, `deleted` | `= default`, `= delete` |
| `accessor`, `accessor_field` | `getter` or `setter`, and its field |

### `t2/cpp_bases.csv`

| column | meaning |
|---|---|
| `derived_name`, `derived_def_file`, `base_name`, `base_def_file` | the pair |
| `position` | the base's place in the class head |
| `virtual`, `access` | as declared |

### `t2/cpp_overrides.csv`

| column | meaning |
|---|---|
| `function_name`, `function_def_file` | the overriding member |
| `overridden_name`, `overridden_def_file` | the virtual function it overrides directly |

### `t2/cpp_slots.csv`

| column | meaning |
|---|---|
| `owner_kind` | `param`, `return`, `field` or `global` |
| `owner_name`, `owner_def_file` | the function, type or global |
| `member`, `member_name` | the parameter's position and name, `ret`, or the field's name |
| `chain` | the type's layers, outermost first |
| `element_name`, `element_def_file` | the user type the chain ends in |
| `type` | the type as written |

A slot whose type is a plain scalar or enum states nothing and has no row,
nor has a slot declared outside the source root.
