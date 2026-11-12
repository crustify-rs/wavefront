#ifndef SYS_H
#define SYS_H

void sys_log(const char *msg);

/* An external header's macro: C's, signature only. */
#define SYS_LOG(m) sys_log(m)

#endif
