/* The translation unit that completes `handle`. */
#include "api.h"

struct handle {
	int refs;
};

int run_impl(options *o, handle *h)
{
	return o->on_handle(h, o->payload) + o->on_count(h->refs, o->payload);
}
