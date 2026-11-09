/* Function pointers written inline and through typedefs, and typedefs of
 * every shape: what `edges/function_pointer_uses.ql` and
 * `edges/function_pointer_signature_types.ql` record, and what the composer
 * folds. Golden tables: function_pointer_uses.csv,
 * function_pointer_signature_types.csv. */
#include <stdint.h>
#include <stddef.h>

struct ctx { int n; };
typedef struct ctx ctx;                   /* same-name alias */
typedef struct ctx ctx_t;                 /* different-name alias */
typedef ctx_t ctx_alias_t;                /* alias of an alias */
typedef int64_t fp_off_t;                 /* primitive, through a system typedef */
typedef fp_off_t fp_pos_t;                /* primitive, through an in-tree one */
typedef void *fp_handle;                  /* a pointer, no tag */

typedef int (*visit_cb)(struct ctx *c, void *payload);   /* declares a fn ptr */
typedef visit_cb visit_alias_cb;                         /* alias of it */

struct ops {
  int (*open)(struct ctx *c, const char *path);   /* inline field */
  void (*close)(struct ctx *c);                    /* inline field */
  visit_cb visit;                                  /* through the typedef */
};

/* inline parameter, and an inline return */
int each(struct ctx *c, int (*fn)(struct ctx *c, void *payload), void *payload) {
  return fn(c, payload);
}
void (*pick(int which))(struct ctx *c) { (void)which; return 0; }

/* inline global, local and cast */
void (*on_exit_hook)(void);
int run(struct ctx *c, void *f) {
  int (*local)(struct ctx *, void *) = (int (*)(struct ctx *, void *))f;
  return local(c, 0);
}

fp_pos_t tell(ctx_alias_t *c, visit_alias_cb cb, fp_handle h) {
  (void)h;
  return cb(c, 0);
}
