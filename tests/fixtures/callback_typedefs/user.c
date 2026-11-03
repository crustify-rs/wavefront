/* A translation unit that sees `handle` only as the header declares it. */
#include "api.h"

int run_user(options *o)
{
	return o->on_handle(o->owner, o->payload) + o->inline_cb(o->owner);
}
