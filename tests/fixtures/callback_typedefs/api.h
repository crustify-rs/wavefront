/* A public header: `handle` is opaque here, as an installed header leaves it. */
typedef struct handle handle;

/* Callbacks whose signatures name the opaque handle, and one that names none. */
typedef int (*handle_cb)(handle *h, void *payload);
typedef int (*count_cb)(int n, void *payload);

typedef struct {
	handle_cb on_handle;
	count_cb on_count;
	int (*inline_cb)(handle *h);
	handle *owner;
	void *payload;
} options;
