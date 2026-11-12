#ifndef ERR_H
#define ERR_H

/* A tagged enum, its constants returned through `int`. */
enum fx_error {
	FX_OK = 0,
	FX_OUT_OF_MEMORY = -2,
	FX_NOT_FOUND = -3
};

/* An untagged enum a typedef names: the typedef is its identity. */
typedef enum {
	FX_KIND_PLAIN,
	FX_KIND_LINK
} fx_kind;

/* An untagged enum no typedef names has no identity, so no rows. */
enum { FX_ANON_LIMIT = 8 };

/* A constant in another enum's initializer has no user. */
enum fx_more { FX_MORE_FIRST = FX_NOT_FOUND - 1 };

/* The replacement list names the constant: the macro's use. */
#define FX_CHECK_ALLOC(p) do { if (!(p)) return FX_OUT_OF_MEMORY; } while (0)

/* The constant an argument passes is the caller's. */
#define FX_PASS(e) (e)

/* A macro naming a constant through a nested macro: the nested one's. */
#define FX_CHECK_TWICE(p, q) do { FX_CHECK_ALLOC(p); FX_CHECK_ALLOC(q); } while (0)

#endif
