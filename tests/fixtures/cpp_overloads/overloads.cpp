// Functions that once shared a key.
//
// `use(left::Tag)` and `use(right::Tag)` collided as `use(Tag)` while
// parameter types were spelled without their scope. `apply(int (*)(left::Tag))`
// and `apply(int (*)(right::Tag))` collided as `apply(..(*)(..))`, CodeQL's
// spelling of any function pointer. `point(left::Tag * const *)` and
// `point(const left::Tag * *)` collided while specifiers were always spelled
// first. The two lambdas' call operators collided as `operator()`, members of
// closure types without a qualified name.
namespace left { struct Tag { int value; }; }
namespace right { struct Tag { double value; }; }
int use(left::Tag tag) { return tag.value; }
int use(right::Tag tag) { return static_cast<int>(tag.value); }
int apply(int (*callback)(left::Tag)) { return callback(left::Tag{3}); }
int apply(int (*callback)(right::Tag)) { return callback(right::Tag{4.0}); }
int point(left::Tag *const *tags) { return (*tags)->value; }
int point(const left::Tag **tags) { return (*tags)->value; }
int both() { return use(left::Tag{1}) + use(right::Tag{2}); }
int callbacks() {
    return apply(static_cast<int (*)(left::Tag)>(use))
         + apply(static_cast<int (*)(right::Tag)>(use));
}
int pointers() {
    left::Tag tag{5};
    left::Tag *mutable_tag = &tag;
    const left::Tag *const_tag = &tag;
    return point(&mutable_tag) + point(&const_tag);
}
int lambdas() {
    auto first = [](int x) { return x + 1; };
    auto second = [](int x) { return x + 2; };
    return first(1) + second(2);
}

// A type and a function in an anonymous namespace are named without it; a
// name starting with `(` would read as an anonymous tag and be dropped.
namespace {
struct Hidden { int value; };
int hide(Hidden hidden) { return hidden.value; }
}
int hidden() { return hide(Hidden{6}); }
