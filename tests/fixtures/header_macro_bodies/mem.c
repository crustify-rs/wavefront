#include <stdlib.h>
#include <string.h>
#include "mem.h"

int mem_live;

/* A translation unit's own macro. */
#define LOCAL_ZERO(p, n) mem_zero((p), (n))

void *mem_alloc(size_t n)
{
	mem_live++;
	return malloc(n);
}

void mem_zero(void *p, size_t n)
{
	memset(p, 0, n);
}

void mem_free(void *p)
{
	free(p);
}

void mem_trace(void *p)
{
	if (p)
		MEM_TRACE(NULL);
}

void *mem_calloc(size_t n)
{
	void *p = mem_alloc(n);
	LOCAL_ZERO(p, n);
	return p;
}
