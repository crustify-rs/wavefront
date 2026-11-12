#ifndef MEM_H
#define MEM_H

#include <stddef.h>

struct pool {
	size_t used;
	size_t cap;
};

void *mem_alloc(size_t n);
void mem_zero(void *p, size_t n);
void mem_free(void *p);
void mem_trace(void *p);
extern int mem_live;

/* A constant: references nothing. */
#define MEM_MAX 4096

/* Logic: calls two functions. */
#define MEM_NEW(x) ((x) = mem_alloc(sizeof(*(x))), mem_zero((x), sizeof(*(x))))

/* A function, a global and a system macro. */
#define MEM_DROP(p) do { mem_free(p); (p) = NULL; mem_live--; } while (0)

/* Other macros only. */
#define MEM_RENEW(x) do { MEM_DROP(x); MEM_NEW(x); } while (0)

/* A field of a type, a cast to it, and a constant. */
#define MEM_POOL_RESET(p) (((struct pool *)(p))->used = (size_t)MEM_MAX)

/* A field of whatever its argument points at: generic, the caller's. */
#define MEM_USED(p) ((p)->used)

struct pool_set {
	struct pool *pools;
	int count;
};

/* Names a field its argument's global shares the name of: the caller's. */
#define MEM_POOL_SET(array) .pools = (array), .count = 1

/* A symbol alias. */
#define mem_release mem_free

/* What it calls is its argument's, not its own. */
#define MEM_APPLY(fn, x) fn(x)

/* Expanded by the function it calls. */
#define MEM_TRACE(p) mem_trace(p)

#endif
