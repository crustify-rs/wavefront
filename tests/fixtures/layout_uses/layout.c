/* Every kind of layout use `edges/layout_uses.ql` records, next to the uses
 * that hold a type only through a pointer and record none. Golden table:
 * layout_uses.csv. */
#include <stddef.h>
#include <string.h>

struct Handle;                       /* opaque: never completed */
struct Point { int x, y; };
typedef struct { int len; char *buf; } Str;   /* shape A: named by its typedef */
struct Base { int refcount; };
struct Node { struct Base base; struct Node *next; struct Point pts[2]; };
struct Conn { struct { int port; } ext; };    /* shape B: an anonymous member */

#define CONTAINER_OF(p, T, m) ((T *)((char *)(p) - offsetof(T, m)))
#define POINT_X(p) ((p)->x)

/* field: read, write and address-of, a macro's expansion included */
int field_read(const struct Point *p) { return p->x; }
void field_write(struct Point *p) { p->y = 1; }
int *field_addr(struct Point *p) { return &p->x; }
int field_macro(struct Point *p) { return POINT_X(p); }
int field_anon(struct Conn *c) { return c->ext.port; }

/* size: sizeof of a type and of an expression, alignof, offsetof */
size_t size_type(void) { return sizeof(struct Point); }
size_t size_expr(struct Point *p) { return sizeof *p; }
size_t size_align(void) { return _Alignof(Str); }
size_t size_offsetof(void) { return offsetof(struct Node, next); }
struct Node *size_container(struct Base *b) { return CONTAINER_OF(b, struct Node, base); }

/* value: by-value locals, parameters, returns, copies, compound literals */
int value_param(struct Point p) { return 0; }
struct Point value_return(void) { struct Point p = {1, 2}; return p; }
void value_copy(struct Point *a, const struct Point *b) { *a = *b; }
int value_literal(void) { return value_param((struct Point){3, 4}); }
void value_memcpy(Str *a, const Str *b) { memcpy(a, b, sizeof *b); }

/* index: pointer arithmetic and indexing over an array of the type */
struct Point *index_add(struct Point *p, int n) { return p + n; }
struct Point *index_incr(struct Point *p) { return ++p; }
int index_subscript(struct Point *p) { return p[2].x; }
long index_diff(struct Point *a, struct Point *b) { return a - b; }

/* globals: by value, and an array of the type, initialized positionally */
struct Point origin = {0, 0};
static Str table[2];

/* none of these depends on a layout */
struct Handle *opaque_pass(struct Handle *h) { return h; }
struct Point *opaque_cast(void *p) { return (struct Point *)p; }
void opaque_null(struct Point **pp) { *pp = NULL; }
int opaque_compare(struct Point *a, struct Point *b) { return a == b; }
