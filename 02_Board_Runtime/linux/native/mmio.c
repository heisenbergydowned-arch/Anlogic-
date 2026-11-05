#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/file.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
struct edge_mapping {int fd;volatile uint32_t *words;};
void *edge_open(const char *path,uint64_t offset) {
    int fd=open(path,O_RDWR|O_SYNC|O_CLOEXEC);if(fd<0)return NULL;
    // Process-level exclusive lock complements the service's thread lock.
    if(flock(fd,LOCK_EX|LOCK_NB)<0){close(fd);return NULL;}
    void *p=mmap(NULL,65536,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)offset);
    if(p==MAP_FAILED){int e=errno;close(fd);errno=e;return NULL;}
    struct edge_mapping *m=calloc(1,sizeof(*m));
    if(!m){munmap(p,65536);close(fd);return NULL;}m->fd=fd;m->words=p;return m;
}
uint32_t edge_read(void *handle,uint32_t offset) {
    struct edge_mapping *m=handle;
    if(!m || (offset&3) || offset>=65536){errno=EINVAL;return 0;}
    __sync_synchronize();uint32_t result=m->words[offset/4];__sync_synchronize();return result;
}
void edge_write(void *handle,uint32_t offset,uint32_t value) {
    struct edge_mapping *m=handle;
    if(!m || (offset&3) || offset>=65536){errno=EINVAL;return;}
    __sync_synchronize();m->words[offset/4]=value;__sync_synchronize();
}
void edge_close(void *handle) {
    struct edge_mapping *m=handle;if(!m)return;
    munmap((void*)m->words,65536);close(m->fd);free(m);
}
