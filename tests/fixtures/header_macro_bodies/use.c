#include "mem.h"
#include "ext/sys.h"

struct widget {
	int id;
};

static struct pool pools[1];
struct pool_set the_set = { MEM_POOL_SET(pools) };

void sys_log(const char *msg)
{
	(void)msg;
}

struct widget *widget_make(struct pool *pool)
{
	struct widget *w;
	char buf[MEM_MAX];

	(void)buf;
	MEM_NEW(w);
	MEM_RENEW(w);
	MEM_POOL_RESET(pool);
	(void)MEM_USED(pool);
	MEM_APPLY(mem_trace, w);
	SYS_LOG("made");
	return w;
}

void widget_drop(struct widget *w)
{
	MEM_DROP(w);
}

void widget_free(struct widget *w)
{
	mem_release(w);
}
