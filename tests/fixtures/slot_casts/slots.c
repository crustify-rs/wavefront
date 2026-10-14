/* Fixture for edges/arg_casts.ql + edges/field_casts.ql. Each block names
 * the rows it must (or must not) produce; tests/test_slot_casts.py pins them. */
#include <stddef.h>

typedef struct Class { const char *name; } Class;
typedef struct CtxA { const Class *cls; int a; } CtxA;
typedef struct CtxB { const Class *cls; int b; } CtxB;
typedef struct Base { int kind; } Base;
typedef struct Derived { Base base; int extra; } Derived;
typedef struct Holder { void *opaque; void *other; Base *typed; } Holder;
typedef struct Payload { int x; } Payload;

/* --- erased parameter chain: CtxA/CtxB -> log.0 -> vlog.0 -> Class ------ */
const char *vlog(void *obj) { return (*(const Class **)obj)->name; } /* to: vlog.0 -> Class */
void log_(void *obj) { vlog(obj); }                                   /* forward: log_.0 -> vlog.0 */
void use_log(CtxA *a, CtxB *b) { log_(a); log_(b); }                  /* from: CtxA, CtxB -> log_.0 */

/* --- typed slot downcast: Base* param read as Derived* ---------------- */
int derived_extra(Base *b) { return ((Derived *)b)->extra; }          /* to: derived_extra.0 -> Derived */

/* --- erased field: Payload written, read back as Payload -------------- */
void put(Holder *h, Payload *p) { h->opaque = p; }                    /* forward: put.1 -> Holder.opaque */
void put_direct(Holder *h, Payload *p) { h->other = (void *)p; }      /* forward: put_direct.1 -> Holder.other */
int get(Holder *h) { return ((Payload *)h->opaque)->x; }              /* to: Holder.opaque -> Payload */
void *get_raw(Holder *h) { return h->opaque; }                        /* forward: Holder.opaque -> get_raw.ret */
int use_raw(Holder *h) { Payload *p = get_raw(h); return p->x; }      /* to: get_raw.ret -> Payload */
void sink(void *v);
void pass_field(Holder *h) { sink(h->opaque); }                       /* forward: Holder.opaque -> sink.0 */
void copy_field(Holder *h) { h->other = h->opaque; }                  /* forward: Holder.opaque -> Holder.other */
void store_local(Holder *h) { Payload p; h->opaque = &p; }            /* from: Payload -> Holder.opaque */

/* --- file-scope designated initializer --------------------------------- */
static Payload g_payload;
static Holder g_holder = { .opaque = &g_payload };                    /* from: Payload -> Holder.opaque */

/* --- must NOT produce rows ---------------------------------------------- */
void reassigned(void *obj, CtxA *fallback) {                          /* reassigned param: no forward, no to */
    if (!obj) obj = fallback;
    vlog(obj);
}
void via_local(void *obj) { void *p = obj; vlog(p); }                 /* through a local: no forward (tier 2) */
void *identity(void *v) { return v; }                                 /* param -> ret: excluded */
int same_type(Base *b) { Base *c = b; return c->kind; }               /* no conversion: no row */
