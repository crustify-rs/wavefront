#include <stddef.h>
#include "err.h"

struct fx_buf {
	char *data;
	size_t len;
	size_t alloc;
};

/* Returns an enum constant through `int`, naming no enum type. */
int fx_buf_grow(struct fx_buf *b, size_t n)
{
	if (b->alloc - b->len < n)
		return FX_OUT_OF_MEMORY;
	return FX_OK;
}

int fx_kind_of(int mode)
{
	switch (mode) {
	case FX_KIND_LINK:
		return 1;
	default:
		return 0;
	}
}

int fx_check(void *p, void *q)
{
	FX_CHECK_TWICE(p, q);
	return FX_PASS(FX_NOT_FOUND);
}

int fx_anon(int n)
{
	return n < FX_ANON_LIMIT;
}

/* Holds the enum's type, names no constant. */
int fx_hold(int v)
{
	enum fx_error e = v;
	return e;
}

/* A global whose initializer names constants. */
const int fx_codes[] = { FX_OUT_OF_MEMORY, FX_NOT_FOUND };
