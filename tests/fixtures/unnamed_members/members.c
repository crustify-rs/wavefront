/* C11 unnamed members (no declarator) next to the anonymous-aggregate shapes
 * the flattening already handled. Golden tables: fields.csv,
 * field_type_uses.csv, fa_with_root.csv. */

typedef struct Level1 { int min; } Level1;
typedef struct Level2 { int max; } Level2;
struct Inner { int v; };

/* AVDOVIDmData: an unnamed union directly in a named struct. */
typedef struct Data {
    int level;
    union {
        Level1 l1;
        Level2 l2;
    };
} Data;

/* AVExpr: function pointers in an unnamed union. */
struct Expr {
    int type;
    union {
        double (*func0)(double);
        double (*func1)(void *, double);
    };
};

/* A named member of anonymous type, holding an unnamed member. */
struct Conn {
    struct {
        int hostname;
        union {
            int port;
            struct Inner *inner;
        };
    } ext;
};

/* Unnamed members nested in each other. */
struct Nest {
    union {
        struct {
            int x;
            int y;
        };
        int z;
    };
};

/* A typedef-named anonymous struct with an unnamed member. */
typedef struct {
    int k;
    union {
        void *p;
        long q;
    };
} Shape;

/* Plain and named-nested members, unaffected. */
struct Plain {
    int a;
    struct Inner in;
};

double use_data(Data *d) { return d->l1.min + d->l2.max + d->level; }
double use_expr(struct Expr *e) { return e->func0(1.0) + e->func1(0, 2.0); }
int use_conn(struct Conn *c) { c->ext.port = 1; return c->ext.hostname + c->ext.inner->v; }
int use_nest(struct Nest *n) { return n->x + n->y + n->z; }
long use_shape(Shape *s) { s->p = 0; return s->q + s->k; }
int use_plain(struct Plain *p) { return p->a + p->in.v; }
