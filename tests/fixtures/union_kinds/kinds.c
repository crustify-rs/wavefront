/* A named union and a typedef-named one, next to a struct and an enum, each
 * used by a field, a global, a local, a signature and a callback signature,
 * so every query that classifies a type says which it is. */
union Num { int i; double d; };
typedef union { long l; void *p; } Word;      /* shape A: named by its typedef */
struct Pair { int a, b; };
enum Tag { TAG_A, TAG_B };

struct Holder { union Num n; Word w; struct Pair p; enum Tag t; };

typedef int (*visit_fn)(union Num *n, Word *w, struct Pair *p, enum Tag t);

union Num g_num;
Word g_word;
struct Pair g_pair;
enum Tag g_tag;

int use(union Num *n, Word *w, struct Pair *p, enum Tag t) {
  union Num ln = *n;
  Word lw = *w;
  struct Pair lp = *p;
  enum Tag lt = t;
  return ln.i + (int)lw.l + lp.a + (int)lt;
}
